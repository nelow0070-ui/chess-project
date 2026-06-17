# Chess Analyzer Mobile PWA

Separate mobile-first PWA prototype. It does not modify the existing Flask app.

## Engine strategy

- Default: browser-side Stockfish through `public/stockfish-worker.js`.
- Optional: server Stockfish API. Set the API base URL in the app settings; it calls `/eval?fen=...`.

## Run

```bash
npm install
npm run dev
```

Open the Vite URL on desktop or on your phone over the same network.

## Server API mode

When `Server Stockfish API` is selected, the app calls:

```text
{SERVER_BASE_URL}/eval?fen={ENCODED_FEN}
```

Expected JSON response:

```json
{ "type": "cp", "cp": 34 }
```

or:

```json
{ "type": "mate", "mate": 3 }
```

If the API is hosted on a different origin from the PWA, it must allow CORS for the PWA origin.

## Production note

The current worker loads Stockfish from UNPKG for quick prototyping. Before app-store/PWA production, download the Stockfish JS/WASM assets into `public/` and update `stockfish-worker.js` to use local files.
