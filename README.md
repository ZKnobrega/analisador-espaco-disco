# Analisador de Espaço em Disco

Aplicativo desktop para Windows (estilo TreeSize) que varre uma unidade ou pasta, calcula o tamanho de cada arquivo e subpasta e ajuda a encontrar o que está ocupando espaço.

## Funcionalidades

- **🌲 Árvore de pastas** com colunas Nome, Tamanho, % do pai (barra visual) e Tipo, ordenada do maior para o menor.
- **📁 Por tipo de arquivo**: filtra todos os arquivos de uma extensão (ex.: `.mp4`), com tamanho e pasta de cada um.
- **Busca por nome** dentro do filtro de tipo.
- **Abrir local** no Explorer (já com o arquivo selecionado), copiar caminho.
- **Exportar CSV** da lista filtrada.
- **Exclusão segura**: sempre pede confirmação e envia para a **Lixeira** (via `send2trash`).
- Varredura em segundo plano (a interface não trava), com botão de cancelar.
- Pastas bloqueadas pelo sistema (ex.: *System Volume Information*) são ignoradas sem erro.

## Requisitos

- Windows 10/11
- Python 3.10 ou superior

## Instalação e uso

```bash
pip install -r requirements.txt
python main.py
```

## Licença

Uso livre.
