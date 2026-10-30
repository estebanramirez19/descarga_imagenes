from flask import Flask, jsonify, render_template_string, request

from app import analyze_url

app = Flask(__name__)


@app.get("/")
def home():
    return render_template_string(
        """
        <!doctype html>
        <html lang="es">
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>Descargador de imágenes</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    background: #f5f7fb;
                    margin: 0;
                    padding: 40px 16px;
                    color: #172033;
                }
                .container {
                    max-width: 760px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 16px;
                    padding: 32px;
                    box-shadow: 0 10px 30px rgba(20, 30, 60, 0.08);
                }
                h1 {
                    margin-top: 0;
                }
                form {
                    display: grid;
                    gap: 16px;
                    margin-top: 24px;
                }
                input, button {
                    width: 100%;
                    box-sizing: border-box;
                    padding: 14px 16px;
                    border-radius: 10px;
                    border: 1px solid #d8dfef;
                    font-size: 16px;
                }
                button {
                    background: #2563eb;
                    color: white;
                    border: none;
                    cursor: pointer;
                    font-weight: 600;
                }
                .result {
                    margin-top: 24px;
                    background: #f8fafc;
                    border: 1px solid #e2e8f0;
                    border-radius: 10px;
                    padding: 16px;
                    white-space: pre-wrap;
                    overflow: auto;
                }
                .error {
                    color: #b91c1c;
                    font-weight: 600;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Descargador de imágenes de productos</h1>
                <p>Ingresa una URL de catálogo o producto para analizarla y devolver los datos detectados.</p>
                <form id="scraper-form">
                    <input id="url" type="url" name="url" placeholder="https://ejemplo.com/producto/123" required />
                    <button type="submit">Analizar</button>
                </form>
                <div id="result" class="result">Esperando URL...</div>
            </div>

            <script>
                const form = document.getElementById('scraper-form');
                const result = document.getElementById('result');

                form.addEventListener('submit', async (event) => {
                    event.preventDefault();
                    const url = document.getElementById('url').value.trim();
                    result.textContent = 'Analizando...';
                    result.classList.remove('error');
                    try {
                        const response = await fetch('/api/analyze', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ url })
                        });
                        const data = await response.json();
                        if (!response.ok) {
                            throw new Error(data.error || 'Error al analizar la URL');
                        }
                        result.textContent = JSON.stringify(data, null, 2);
                    } catch (error) {
                        result.textContent = error.message;
                        result.classList.add('error');
                    }
                });
            </script>
        </body>
        </html>
        """
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or request.form.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Debes enviar una URL válida."}), 400

    try:
        products = analyze_url(url)
        return jsonify({"products": products})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
