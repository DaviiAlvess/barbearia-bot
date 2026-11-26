# Catálogo de Animes e Mangás

Trabalho de DAVI ALMEIDA DOS SANTOS ALVES.

Catálogo em uma página, em português, para buscar animes e mangás. Os dados vêm da [Jikan API](https://jikan.moe/) (MyAnimeList não oficial, gratuito, sem chave).

## O que a página faz

- Busca por nome, com alternância entre anime e mangá.
- Filtros de gênero e status (`genres` e `status` da Jikan).
- Grade de cards com capa, nota, sinopse curta e quantidade de episódios ou capítulos.
- Modal com a ficha completa, trailer ou link do MyAnimeList quando a API envia.
- Estado de carregamento e estado de erro com botão para tentar de novo.
- A busca é atrasada (debounce) e as requisições saem com intervalo, para respeitar o limite de cerca de 3 por segundo.

## Publicação

O site para o GitHub Pages está no branch `cursor/catalogo-pages-61fd`, com estes mesmos arquivos na raiz. Para ligar a publicação: em Settings → Pages, escolha Deploy from a branch, o branch `cursor/catalogo-pages-61fd` e a pasta `/ (root)`.

Não faça merge desse branch no `main`. Ele existe só para servir o catálogo.

## Como abrir

Os scripts são módulos ES6 e precisam de HTTP. Na pasta `catalogo-animes`:

```bash
python3 -m http.server 8080
```

Depois abra `http://127.0.0.1:8080`.

## Arquivos

- `index.html` — estrutura da página
- `css/styles.css` — layout com Flexbox e Grid
- `js/api.js` — consultas à Jikan e fila de requisições
- `js/labels.js` — textos em português
- `js/render.js` — atualização do DOM
- `js/main.js` — busca, filtros e modal
