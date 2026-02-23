from flask import Flask, request, render_template, jsonify
import json
try:
    from api.dex import *  # package-style import
except ModuleNotFoundError:
    from dex import *  # file-style import when /app/api is cwd

app = Flask(__name__, template_folder='../templates')

BASE_WS_URL = "wss://io.dexscreener.com/dex/screener/v5/pairs/h24/1?rankBy[key]=trendingScoreH6&rankBy[order]=desc"


def _build_ws_url(generated_text: str) -> str:
    text = BASE_WS_URL
    if generated_text:
        text += generated_text
    return text


def _fetch_trends(generated_text: str):
    ws_url = _build_ws_url(generated_text)
    new_bot = DexBot(Api, ws_url)
    mes = new_bot.format_token_data()
    return json.loads(mes)



@app.route('/', methods=['GET'])
def root():
    return render_template("index.html")

@app.route('/dex', methods=['GET'])
def dex():
    try:
        generated_text = request.args.get('generated_text', '')
        result = _fetch_trends(generated_text)

        # Format the response JSON nicely for display
        mes_json = json.dumps(result, indent=4)

        return render_template("dex.html", mes=mes_json)
            
    except Exception as e:
        print(e)
        return f'''
            <body style="background-color:black; color:red; font-family: Arial, sans-serif; text-align: center; padding: 20px;">
                <h2>Error occurred</h2>
                <p>{str(e)}</p>
                <p>Unable to send message.</p>
            </body>
        '''


@app.route('/api/trends', methods=['GET'])
def trends_api():
    try:
        generated_text = request.args.get('generated_text', '')
        result = _fetch_trends(generated_text)
        return jsonify(result)
    except Exception as e:
        return jsonify({"data": [], "error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
