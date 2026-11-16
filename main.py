"""
Analisador de Espaço em Disco (estilo TreeSize)
================================================

Aplicativo desktop para Windows com interface gráfica moderna que varre
um diretório/unidade, calcula o tamanho de cada arquivo e pasta e exibe a
hierarquia em árvore, permitindo excluir itens com segurança (enviando para
a Lixeira via send2trash).

Abas:
  * "🌲 Árvore"        — hierarquia de pastas com barra de proporção (% do pai).
  * "📁 Por Tipo"      — filtra todos os arquivos de um formato (ex.: .mp4),
                         mostra tamanho e a pasta de cada um, abre o local,
                         exclui e exporta para CSV.

Características:
  * GUI em PySide6 (Qt) com tema escuro moderno.
  * Varredura recursiva em uma thread separada (QThread) — a interface
    nunca congela, mesmo em discos grandes.
  * Itens de 0 bytes são ocultados; ordenação decrescente por tamanho.
  * Exclusão via botão, menu de contexto (botão direito) ou tecla Delete,
    sempre com confirmação. Usa a Lixeira do Windows quando possível.
  * Erros de permissão (PermissionError) e pastas bloqueadas são
    ignorados silenciosamente para não travar a varredura.

Dependências:
    pip install PySide6 Send2Trash
"""

import os
import sys
import csv
import shutil
import subprocess

from PySide6.QtCore import Qt, QThread, Signal, QRect, QSize, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

# ---------------------------------------------------------------------------
# send2trash é opcional: se não estiver instalado, caímos para exclusão
# permanente (com aviso reforçado na confirmação).
# ---------------------------------------------------------------------------
try:
    from send2trash import send2trash

    HAVE_SEND2TRASH = True
except ImportError:  # pragma: no cover - depende do ambiente
    HAVE_SEND2TRASH = False

# Diretórios muito profundos são raros, mas elevamos um pouco o limite de
# recursão por segurança. Symlinks/junctions são ignorados na varredura,
# então não há risco de loops infinitos.
sys.setrecursionlimit(5000)
_MAX_DEPTH = 4000          # guarda extra contra estouro de pilha
_FLAT_LIMIT = 3000         # máx. de linhas exibidas na aba "Por Tipo"
_NO_EXT = "(sem extensão)"

# Cor de destaque da interface
ACCENT = "#4c8bf5"


# ===========================================================================
# Folha de estilo (QSS) — tema escuro moderno
# ===========================================================================
STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
    color: #d7dce5;
}}
QMainWindow, QWidget {{ background-color: #1b1e24; }}

QLabel {{ color: #aeb6c2; background: transparent; }}
QLabel#title {{ font-size: 17pt; font-weight: 700; color: #f0f3f8; }}
QLabel#subtitle {{ color: #6b7382; font-size: 9pt; }}
QLabel#summary {{ color: #aeb6c2; padding: 2px 2px; }}

QLineEdit, QComboBox {{
    background-color: #262b34;
    border: 1px solid #353c47;
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: #262b34;
    border: 1px solid #353c47;
    selection-background-color: {ACCENT};
    outline: 0;
}}

QPushButton {{
    background-color: #2b313b;
    border: 1px solid #3a424e;
    border-radius: 6px;
    padding: 7px 14px;
    color: #e3e8ef;
}}
QPushButton:hover {{ background-color: #343b47; border-color: {ACCENT}; }}
QPushButton:pressed {{ background-color: #232831; }}
QPushButton:disabled {{ color: #5e6675; background-color: #23272f; border-color: #2d333d; }}

QPushButton#primary {{ background-color: {ACCENT}; border: none; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background-color: #5d97f7; }}
QPushButton#primary:pressed {{ background-color: #3f78d8; }}
QPushButton#danger:hover {{ background-color: #5a2f33; border-color: #e0625e; color: #ffd9d7; }}

QTabWidget::pane {{ border: 1px solid #2d333d; border-radius: 8px; top: -1px; }}
QTabBar::tab {{
    background: #20242c; color: #9aa3b1; padding: 8px 18px;
    border: 1px solid #2d333d; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}}
QTabBar::tab:selected {{ background: #262b34; color: #f0f3f8; }}
QTabBar::tab:hover {{ color: #d7dce5; }}

QTreeWidget {{
    background-color: #20242c;
    alternate-background-color: #242931;
    border: 1px solid #2d333d;
    border-radius: 8px;
    outline: 0;
}}
QTreeWidget::item {{ padding: 5px 2px; border: none; }}
QTreeWidget::item:selected {{ background-color: #34507e; color: #ffffff; }}
QTreeWidget::item:hover {{ background-color: #2a303a; }}

QHeaderView::section {{
    background-color: #262b34;
    color: #9aa3b1;
    padding: 7px 8px;
    border: none;
    border-right: 1px solid #2d333d;
    border-bottom: 1px solid #2d333d;
    font-weight: 600;
}}
QHeaderView::section:hover {{ color: #d7dce5; }}

QProgressBar {{
    border: 1px solid #2d333d;
    border-radius: 6px;
    background: #20242c;
    text-align: center;
    color: #aeb6c2;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 6px; }}

QStatusBar {{ background: #181b20; color: #9aa3b1; }}
QStatusBar::item {{ border: none; }}

QMenu {{ background: #262b34; border: 1px solid #353c47; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::separator {{ height: 1px; background: #353c47; margin: 4px 8px; }}

QToolTip {{ background: #262b34; color: #d7dce5; border: 1px solid {ACCENT}; padding: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3a424e; border-radius: 6px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #3a424e; border-radius: 6px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


# ===========================================================================
# Modelo de dados e utilitários
# ===========================================================================
class Node:
    """Representa um arquivo ou pasta na árvore varrida."""

    __slots__ = ("name", "path", "is_dir", "size", "children", "parent")

    def __init__(self, name, path, is_dir, parent=None):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = 0          # tamanho total em bytes (recursivo, para pastas)
        self.children = []
        self.parent = parent


def format_size(num_bytes):
    """Converte bytes em uma string legível (B, KB, MB, GB, ...)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024.0:
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} EB"


def percent_of_parent(node):
    """Fração (0..1) do tamanho do nó em relação à pasta-pai."""
    if node.parent is not None and node.parent.size > 0:
        return node.size / node.parent.size
    return 1.0


def bar_color(pct):
    """Cor da barra: verde-azulado (pequeno) -> vermelho (grande)."""
    pct = max(0.0, min(1.0, pct))
    hue = (160.0 * (1.0 - pct)) / 360.0  # 160°=verde-azulado, 0°=vermelho
    color = QColor()
    color.setHsvF(hue, 0.65, 0.85)
    return color


def file_ext(node):
    """Extensão em minúsculas (com ponto) ou rótulo para arquivos sem extensão."""
    return os.path.splitext(node.name)[1].lower() or _NO_EXT


def type_label(node):
    """Rótulo legível de tipo: 'Pasta' ou 'Arquivo PDF'."""
    if node.is_dir:
        return "Pasta"
    ext = os.path.splitext(node.name)[1].lstrip(".").upper()
    return f"Arquivo {ext}" if ext else "Arquivo"


def iter_files(node):
    """Itera (sem recursão) todos os arquivos com tamanho > 0 sob `node`."""
    stack = [node]
    while stack:
        n = stack.pop()
        if n.is_dir:
            stack.extend(n.children)
        elif n.size > 0:
            yield n


# ===========================================================================
# Worker de varredura (executa em thread separada)
# ===========================================================================
class ScanWorker(QThread):
    progress = Signal(int, int, str)   # arquivos, pastas, caminho atual
    finished_scan = Signal(object)     # nó raiz já preenchido
    error = Signal(str)                # mensagem de erro fatal

    def __init__(self, root_path):
        super().__init__()
        self.root_path = root_path
        self._cancel = False
        self._file_count = 0
        self._folder_count = 0
        self._last_emit = 0

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            if not os.path.isdir(self.root_path):
                self.error.emit(f"Caminho inválido ou inacessível:\n{self.root_path}")
                return
            name = os.path.basename(self.root_path.rstrip("\\/")) or self.root_path
            root = Node(name, self.root_path, True)
            self._scan(root, depth=0)
            if not self._cancel:
                self.progress.emit(self._file_count, self._folder_count, self.root_path)
                self.finished_scan.emit(root)
        except Exception as exc:  # rede de segurança — nunca derruba a thread
            self.error.emit(str(exc))

    def _scan(self, node, depth):
        """Varre recursivamente `node` e devolve o tamanho total em bytes."""
        if self._cancel or depth > _MAX_DEPTH:
            return 0

        total = 0
        try:
            with os.scandir(node.path) as it:
                for entry in it:
                    if self._cancel:
                        break
                    try:
                        # Ignora symlinks/junctions: evita loops e contagem dupla.
                        if entry.is_symlink():
                            continue

                        if entry.is_dir(follow_symlinks=False):
                            child = Node(entry.name, entry.path, True, node)
                            self._folder_count += 1
                            child.size = self._scan(child, depth + 1)
                            node.children.append(child)
                            total += child.size
                        else:
                            try:
                                sz = entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                sz = 0
                            child = Node(entry.name, entry.path, False, node)
                            child.size = sz
                            self._file_count += 1
                            node.children.append(child)
                            total += sz
                    except (PermissionError, OSError):
                        continue  # item individual bloqueado — ignora
        except (PermissionError, OSError):
            pass  # pasta inteira bloqueada (ex.: System Volume Information)

        # Emite progresso "throttled" para não inundar a fila de sinais.
        if self._folder_count - self._last_emit >= 50:
            self._last_emit = self._folder_count
            self.progress.emit(self._file_count, self._folder_count, node.path)

        node.size = total
        return total


# ===========================================================================
# Delegate que desenha a barra de proporção (% do pai)
# ===========================================================================
class BarDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # Desenha o fundo padrão (seleção/linhas alternadas) sem o texto,
        # respeitando o tema definido pela folha de estilo.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        node = index.data(Qt.ItemDataRole.UserRole)
        if node is None:
            return

        pct = percent_of_parent(node)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = option.rect.adjusted(8, 5, -8, -6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22))   # trilho de fundo
        painter.drawRoundedRect(rect, 4, 4)
        clamped = max(0.0, min(1.0, pct))
        w = int(round(rect.width() * clamped))
        if w > 0:
            fill = QRect(rect.left(), rect.top(), max(w, 3), rect.height())
            painter.setBrush(bar_color(clamped))
            painter.drawRoundedRect(fill, 4, 4)
        painter.setPen(QColor("#ffffff") if (opt.state & QStyle.StateFlag.State_Selected)
                       else QColor("#e6eaf1"))
        font = painter.font()
        font.setPointSizeF(8.5)
        painter.setFont(font)
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, f"{pct * 100:.1f}%")
        painter.restore()


# ===========================================================================
# Itens de árvore com ordenação numérica correta
# ===========================================================================
class SizeItem(QTreeWidgetItem):
    """Item da árvore hierárquica (colunas: Nome, Tamanho, % do Pai, Tipo)."""

    def __init__(self, node):
        super().__init__()
        self.node = node
        self.populated = not node.is_dir  # arquivos já estão "completos"

    def __lt__(self, other):
        if not isinstance(other, SizeItem):
            return super().__lt__(other)
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 1
        if column == 0:
            return self.node.name.lower() < other.node.name.lower()
        if column == 2:
            return percent_of_parent(self.node) < percent_of_parent(other.node)
        if column == 3:
            return self.text(3).lower() < other.text(3).lower()
        return self.node.size < other.node.size


class FlatItem(QTreeWidgetItem):
    """Item da lista plana 'Por Tipo' (colunas: Nome, Tamanho, Tipo, Local)."""

    def __init__(self, node):
        super().__init__()
        self.node = node

    def __lt__(self, other):
        if not isinstance(other, FlatItem):
            return super().__lt__(other)
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 1
        if column == 1:
            return self.node.size < other.node.size
        return self.text(column).lower() < other.text(column).lower()


# ===========================================================================
# Janela principal
# ===========================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Analisador de Espaço em Disco")
        self.resize(980, 660)

        self.worker = None
        self.root_node = None
        self.all_files = []   # lista plana de Nodes de arquivos (size > 0)

        style = self.style()
        self._dir_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        self._build_ui()
        self._populate_drives()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        # --- Cabeçalho ---
        title = QLabel("📊  Analisador de Espaço em Disco")
        title.setObjectName("title")
        subtitle = QLabel("Visualize o que está ocupando espaço e remova com segurança.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # --- Controles de varredura (compartilhados) ---
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Unidade:"))
        self.drive_combo = QComboBox()
        self.drive_combo.setToolTip("Unidades disponíveis")
        self.drive_combo.currentTextChanged.connect(self._on_drive_selected)
        controls.addWidget(self.drive_combo)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Selecione uma pasta ou unidade para analisar...")
        self.path_edit.returnPressed.connect(self.start_scan)
        controls.addWidget(self.path_edit, 1)

        self.browse_btn = QPushButton("Procurar pasta…")
        self.browse_btn.clicked.connect(self._browse)
        controls.addWidget(self.browse_btn)

        self.scan_btn = QPushButton("Escanear")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(self.start_scan)
        controls.addWidget(self.scan_btn)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self._cancel_scan)
        self.cancel_btn.setEnabled(False)
        controls.addWidget(self.cancel_btn)
        layout.addLayout(controls)

        # --- Abas ---
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tree_tab(), "🌲  Árvore")
        self.tabs.addTab(self._build_files_tab(), "📁  Por Tipo de Arquivo")
        layout.addWidget(self.tabs, 1)

        # --- Barra de status + progresso ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # modo indeterminado ("escaneando…")
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(180)
        self.status_label = QLabel("Pronto.")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)

    def _build_tree_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 10, 8, 8)
        v.setSpacing(8)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.tree_delete_btn = QPushButton("🗑  Excluir selecionado")
        self.tree_delete_btn.setObjectName("danger")
        self.tree_delete_btn.clicked.connect(self._delete_from_tree)
        self.tree_delete_btn.setEnabled(False)
        actions.addWidget(self.tree_delete_btn)
        self.tree_open_btn = QPushButton("Abrir local")
        self.tree_open_btn.clicked.connect(self._open_from_tree)
        self.tree_open_btn.setEnabled(False)
        actions.addWidget(self.tree_open_btn)
        actions.addStretch(1)
        v.addLayout(actions)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Nome", "Tamanho", "% do Pai", "Tipo"])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.tree.setItemDelegateForColumn(2, BarDelegate(self.tree))
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._open_node_location(it.node))
        self.tree.itemSelectionChanged.connect(
            lambda: self._toggle(self.tree_delete_btn, self.tree_open_btn,
                                 enabled=bool(self.tree.selectedItems())))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)

        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 150)
        self.tree.setColumnWidth(3, 130)
        v.addWidget(self.tree, 1)

        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree, self._delete_from_tree)
        return page

    def _build_files_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 10, 8, 8)
        v.setSpacing(8)

        # Linha de filtro
        flt = QHBoxLayout()
        flt.setSpacing(8)
        flt.addWidget(QLabel("Tipo:"))
        self.ext_combo = QComboBox()
        self.ext_combo.setMinimumWidth(280)
        self.ext_combo.setToolTip("Filtrar por extensão de arquivo")
        self.ext_combo.currentIndexChanged.connect(self._refresh_files_view)
        flt.addWidget(self.ext_combo)

        flt.addWidget(QLabel("Buscar:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("parte do nome do arquivo…")
        self.search_edit.setClearButtonEnabled(True)
        flt.addWidget(self.search_edit, 1)

        self.export_btn = QPushButton("Exportar CSV")
        self.export_btn.clicked.connect(self._export_csv)
        flt.addWidget(self.export_btn)
        v.addLayout(flt)

        # Filtro de busca com pequeno atraso (debounce)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(250)
        self._filter_timer.timeout.connect(self._refresh_files_view)
        self.search_edit.textChanged.connect(lambda _t: self._filter_timer.start())

        self.files_summary = QLabel("Faça uma varredura para listar os arquivos.")
        self.files_summary.setObjectName("summary")
        v.addWidget(self.files_summary)

        # Ações
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.files_delete_btn = QPushButton("🗑  Excluir selecionado")
        self.files_delete_btn.setObjectName("danger")
        self.files_delete_btn.clicked.connect(self._delete_from_files)
        self.files_delete_btn.setEnabled(False)
        actions.addWidget(self.files_delete_btn)
        self.files_open_btn = QPushButton("Abrir local")
        self.files_open_btn.clicked.connect(self._open_from_files)
        self.files_open_btn.setEnabled(False)
        actions.addWidget(self.files_open_btn)
        actions.addStretch(1)
        v.addLayout(actions)

        # Tabela plana
        self.files_tree = QTreeWidget()
        self.files_tree.setColumnCount(4)
        self.files_tree.setHeaderLabels(["Nome", "Tamanho", "Tipo", "Local (pasta)"])
        self.files_tree.setRootIsDecorated(False)
        self.files_tree.setUniformRowHeights(True)
        self.files_tree.setAlternatingRowColors(True)
        self.files_tree.setIconSize(QSize(18, 18))
        self.files_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files_tree.setSortingEnabled(True)
        self.files_tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.files_tree.itemDoubleClicked.connect(lambda it, _c: self._open_node_location(it.node))
        self.files_tree.itemSelectionChanged.connect(
            lambda: self._toggle(self.files_delete_btn, self.files_open_btn,
                                 enabled=bool(self.files_tree.selectedItems())))
        self.files_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files_tree.customContextMenuRequested.connect(self._files_context_menu)

        fheader = self.files_tree.header()
        fheader.setStretchLastSection(True)
        fheader.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.files_tree.setColumnWidth(0, 300)
        self.files_tree.setColumnWidth(1, 110)
        self.files_tree.setColumnWidth(2, 120)
        v.addWidget(self.files_tree, 1)

        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.files_tree, self._delete_from_files)
        return page

    @staticmethod
    def _toggle(*buttons, enabled):
        for b in buttons:
            b.setEnabled(enabled)

    def _populate_drives(self):
        drives = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append(root)
        self.drive_combo.blockSignals(True)
        self.drive_combo.clear()
        self.drive_combo.addItems(drives)
        self.drive_combo.blockSignals(False)
        if drives:
            self.path_edit.setText(drives[0])

    # --------------------------------------------------------------- eventos
    def _on_drive_selected(self, drive):
        if drive:
            self.path_edit.setText(drive)

    def _browse(self):
        start = self.path_edit.text() or ""
        folder = QFileDialog.getExistingDirectory(self, "Selecione a pasta", start)
        if folder:
            self.path_edit.setText(os.path.normpath(folder))

    # ------------------------------------------------------------ varredura
    def start_scan(self):
        if self.worker is not None and self.worker.isRunning():
            return
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.information(self, "Atenção", "Informe uma pasta ou unidade.")
            return
        if not os.path.isdir(path):
            QMessageBox.warning(self, "Atenção", f"Caminho inválido:\n{path}")
            return

        self.tree.clear()
        self.files_tree.clear()
        self.ext_combo.blockSignals(True)
        self.ext_combo.clear()
        self.ext_combo.blockSignals(False)
        self.all_files = []
        self.root_node = None
        self.files_summary.setText("Escaneando…")
        self._set_scanning(True)
        self.status_label.setText("Escaneando…")

        self.worker = ScanWorker(path)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_scan.connect(self._on_scan_finished)
        self.worker.error.connect(self._on_scan_error)
        self.worker.finished.connect(self._on_thread_finished)
        self.worker.start()

    def _cancel_scan(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("Cancelando…")

    def _set_scanning(self, scanning):
        self.progress.setVisible(scanning)
        self.scan_btn.setEnabled(not scanning)
        self.browse_btn.setEnabled(not scanning)
        self.drive_combo.setEnabled(not scanning)
        self.path_edit.setEnabled(not scanning)
        self.cancel_btn.setEnabled(scanning)

    def _on_progress(self, files, folders, current_path):
        short = current_path if len(current_path) <= 70 else "…" + current_path[-67:]
        self.status_label.setText(
            f"Escaneando… {folders:,} pastas, {files:,} arquivos — {short}"
        )

    def _on_scan_finished(self, root):
        self.root_node = root

        # Aba Árvore
        root_item = self._create_item(root)
        root_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        root_item.populated = False
        self.tree.addTopLevelItem(root_item)
        self.tree.expandItem(root_item)

        # Aba Por Tipo
        self.all_files = list(iter_files(root))
        self._build_ext_index()
        self._refresh_files_view()

        self.status_label.setText(
            f"Concluído: {format_size(root.size)} — "
            f"{self.worker._folder_count:,} pastas, {self.worker._file_count:,} arquivos."
        )

    def _on_scan_error(self, message):
        QMessageBox.critical(self, "Erro na varredura", message)
        self.status_label.setText("Erro na varredura.")
        self.files_summary.setText("Erro na varredura.")

    def _on_thread_finished(self):
        self._set_scanning(False)
        if self.status_label.text() == "Cancelando…":
            self.status_label.setText("Varredura cancelada.")

    # ----------------------------------------------------- aba Árvore (lazy)
    def _create_item(self, node):
        item = SizeItem(node)
        item.setText(0, node.name)
        item.setText(1, format_size(node.size))
        item.setData(2, Qt.ItemDataRole.UserRole, node)  # usado pelo BarDelegate
        item.setText(3, type_label(node))
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setIcon(0, self._dir_icon if node.is_dir else self._file_icon)
        if node.is_dir:
            if any(c.size > 0 for c in node.children):
                item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
                item.populated = False
            else:
                item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
                item.populated = True
        return item

    def _on_item_expanded(self, item):
        if not isinstance(item, SizeItem) or item.populated:
            return
        # Oculta itens de 0 byte; a ordenação é aplicada automaticamente.
        for child in item.node.children:
            if child.size > 0:
                item.addChild(self._create_item(child))
        item.populated = True

    # ------------------------------------------------ aba Por Tipo de Arquivo
    def _build_ext_index(self):
        """(Re)constrói o combo de extensões a partir de self.all_files."""
        previous = self.ext_combo.currentData() if self.ext_combo.count() else None
        agg = {}
        for f in self.all_files:
            ext = file_ext(f)
            slot = agg.setdefault(ext, [0, 0])
            slot[0] += 1
            slot[1] += f.size
        ordered = sorted(agg.items(), key=lambda kv: kv[1][1], reverse=True)

        self.ext_combo.blockSignals(True)
        self.ext_combo.clear()
        total_count = sum(v[0] for v in agg.values())
        total_size = sum(v[1] for v in agg.values())
        self.ext_combo.addItem(
            f"Todos os tipos — {total_count:,} arquivos · {format_size(total_size)}", None
        )
        restore = 0
        for i, (ext, (count, size)) in enumerate(ordered, start=1):
            self.ext_combo.addItem(f"{ext} — {count:,} arquivos · {format_size(size)}", ext)
            if ext == previous:
                restore = i
        self.ext_combo.setCurrentIndex(restore)
        self.ext_combo.blockSignals(False)

    def _current_matches(self):
        """Arquivos que satisfazem o filtro atual (extensão + busca), ordenados."""
        if not self.all_files:
            return []
        ext = self.ext_combo.currentData()
        query = self.search_edit.text().strip().lower()
        out = []
        for f in self.all_files:
            if ext is not None and file_ext(f) != ext:
                continue
            if query and query not in f.name.lower():
                continue
            out.append(f)
        out.sort(key=lambda n: n.size, reverse=True)
        return out

    def _refresh_files_view(self):
        matches = self._current_matches()
        total = sum(f.size for f in matches)
        shown = matches[:_FLAT_LIMIT]

        self.files_tree.setSortingEnabled(False)
        self.files_tree.clear()
        for n in shown:
            item = FlatItem(n)
            item.setText(0, n.name)
            item.setText(1, format_size(n.size))
            item.setText(2, type_label(n))
            item.setText(3, os.path.dirname(n.path))
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setIcon(0, self._file_icon)
            self.files_tree.addTopLevelItem(item)
        self.files_tree.setSortingEnabled(True)
        self.files_tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)

        if not self.all_files:
            self.files_summary.setText("Faça uma varredura para listar os arquivos.")
        else:
            txt = f"{len(matches):,} arquivos · {format_size(total)}"
            if len(matches) > _FLAT_LIMIT:
                txt += f"   (mostrando os {_FLAT_LIMIT:,} maiores)"
            self.files_summary.setText(txt)

    def _export_csv(self):
        matches = self._current_matches()
        if not matches:
            QMessageBox.information(self, "Exportar CSV", "Não há arquivos para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar lista para CSV", "arquivos.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh, delimiter=";")
                writer.writerow(["Nome", "Tamanho (bytes)", "Tamanho", "Tipo", "Caminho"])
                for n in matches:
                    writer.writerow([n.name, n.size, format_size(n.size), type_label(n), n.path])
        except Exception as exc:
            QMessageBox.warning(self, "Erro", f"Não foi possível salvar o CSV:\n{exc}")
            return
        self.status_label.setText(f"Exportado: {len(matches):,} arquivos → {path}")

    # ----------------------------------------------------------- exclusão
    def _delete_from_tree(self):
        nodes = [it.node for it in self.tree.selectedItems() if isinstance(it, SizeItem)]
        self._delete_nodes(nodes)

    def _delete_from_files(self):
        nodes = [it.node for it in self.files_tree.selectedItems() if isinstance(it, FlatItem)]
        self._delete_nodes(nodes)

    def _delete_nodes(self, nodes):
        if not nodes:
            return

        # Remove descendentes cujo ancestral também foi selecionado.
        nodeset = set(nodes)
        targets = []
        for n in nodes:
            p, redundant = n.parent, False
            while p is not None:
                if p in nodeset:
                    redundant = True
                    break
                p = p.parent
            if not redundant:
                targets.append(n)

        if HAVE_SEND2TRASH:
            destino = "Os itens serão enviados para a Lixeira do Windows."
        else:
            destino = ("⚠ A biblioteca 'send2trash' não está instalada — os itens "
                       "serão EXCLUÍDOS PERMANENTEMENTE (sem Lixeira).")
        if len(targets) == 1:
            pergunta = f"Tem certeza que deseja excluir:\n\n{targets[0].path}\n\n{destino}"
        else:
            pergunta = f"Tem certeza que deseja excluir {len(targets)} itens?\n\n{destino}"

        reply = QMessageBox.question(
            self, "Confirmar exclusão", pergunta,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted, errors = [], []
        for node in targets:
            try:
                if HAVE_SEND2TRASH:
                    send2trash(node.path)
                elif node.is_dir:
                    shutil.rmtree(node.path)
                else:
                    os.remove(node.path)
            except Exception as exc:
                errors.append(f"{node.path}\n  -> {exc}")
                continue

            # Atualiza os tamanhos dos ancestrais no modelo de dados.
            deleted_size = node.size
            p = node.parent
            while p is not None:
                p.size -= deleted_size
                p = p.parent
            if node.parent is not None and node in node.parent.children:
                node.parent.children.remove(node)
            deleted.append(node)

        if deleted:
            self._apply_deletions(deleted)
        if errors:
            QMessageBox.warning(self, "Alguns itens não foram excluídos", "\n\n".join(errors))

    def _apply_deletions(self, deleted):
        """Sincroniza ambas as abas após excluir `deleted` (nós-raiz removidos)."""
        # 1) Remove os arquivos afetados da lista plana.
        removed_files = set()
        for node in deleted:
            removed_files.update(iter_files(node))
        if removed_files:
            self.all_files = [f for f in self.all_files if f not in removed_files]

        # 2) Atualiza a árvore: tamanhos dos sobreviventes e remoção dos excluídos.
        deleted_ids = {id(n) for n in deleted}
        to_remove = []
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if isinstance(item, SizeItem):
                if id(item.node) in deleted_ids:
                    to_remove.append(item)
                else:
                    item.setText(1, format_size(item.node.size))
            iterator += 1
        for item in to_remove:
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)
            else:
                idx = self.tree.indexOfTopLevelItem(item)
                if idx >= 0:
                    self.tree.takeTopLevelItem(idx)
        self.tree.viewport().update()

        # 3) Reconstrói o índice de tipos e a lista plana.
        self._build_ext_index()
        self._refresh_files_view()

    # ------------------------------------------------------- abrir / copiar
    def _open_from_tree(self):
        items = self.tree.selectedItems()
        if items:
            self._open_node_location(items[0].node)

    def _open_from_files(self):
        items = self.files_tree.selectedItems()
        if items:
            self._open_node_location(items[0].node)

    def _open_node_location(self, node):
        try:
            if node.is_dir:
                os.startfile(node.path)  # abre a pasta
            else:
                # abre o Explorer já com o arquivo selecionado
                subprocess.run(["explorer", "/select,", os.path.normpath(node.path)])
        except Exception as exc:
            QMessageBox.warning(self, "Erro", f"Não foi possível abrir:\n{exc}")

    def _copy_path(self, node):
        if node is not None:
            QApplication.clipboard().setText(node.path)
            self.status_label.setText(f"Caminho copiado: {node.path}")

    # ----------------------------------------------------- menus de contexto
    def _tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self._build_context_menu(self.tree.viewport().mapToGlobal(pos),
                                 item.node, self._delete_from_tree)

    def _files_context_menu(self, pos):
        item = self.files_tree.itemAt(pos)
        if item is None:
            return
        self._build_context_menu(self.files_tree.viewport().mapToGlobal(pos),
                                 item.node, self._delete_from_files)

    def _build_context_menu(self, global_pos, node, delete_callback):
        menu = QMenu(self)
        act_open = QAction("Abrir local no Explorer", self)
        act_open.triggered.connect(lambda: self._open_node_location(node))
        menu.addAction(act_open)
        act_copy = QAction("Copiar caminho", self)
        act_copy.triggered.connect(lambda: self._copy_path(node))
        menu.addAction(act_copy)
        menu.addSeparator()
        act_del = QAction("Excluir", self)
        act_del.triggered.connect(delete_callback)
        menu.addAction(act_del)
        menu.exec(global_pos)

    # ------------------------------------------------------------- fechamento
    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # base neutra para o tema escuro
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
