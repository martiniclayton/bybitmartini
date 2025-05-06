from flask import Flask, request
import requests
import pandas as pd
import time
import threading
from datetime import datetime
from pybit.unified_trading import HTTP
import os

app = Flask(__name__)

# Configurações
BOT_TOKEN = '7723343194:AAEpgCrA6mymE5VeSv2DDdQ6sAVvVMJvCYc'
CHAT_ID = '948274284'
client = HTTP(testnet=False)

operacao_ativa = False
tipo_operacao = None
preco_entrada = 0.0
preco_alvo = 0.0
preco_stop = 0.0
operacoes_realizadas = 0
lucro_total = 0.0
relatorio_operacoes = []
tempo_ultima_operacao = 0

# Taxas estimadas
taxa_compra = 0.0004
taxa_venda = 0.0004
lucro_desejado = 0.005 + taxa_compra + taxa_venda
perda_maxima = 0.005

def enviar_mensagem(msg):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = {'chat_id': CHAT_ID, 'text': msg}
    requests.post(url, data=data)

def pegar_dados():
    response = client.get_kline(
        category="linear",
        symbol="SOLUSDT",
        interval="5",
        limit=50
    )
    df = pd.DataFrame(response["result"]["list"], columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'
    ])
    df['close'] = df['close'].astype(float)
    df = df[::-1].reset_index(drop=True)
    return df

def analisar(df):
    df['EMA9'] = df['close'].ewm(span=9).mean()
    df['EMA21'] = df['close'].ewm(span=21).mean()
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    rs = up.rolling(6).mean() / down.rolling(6).mean()
    df['RSI6'] = 100 - (100 / (1 + rs))
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['Signal'] = df['MACD'].ewm(span=9).mean()
    return df

def preco_atual():
    df = pegar_dados()
    return df['close'].iloc[-1]

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    global operacao_ativa, tipo_operacao, preco_entrada, preco_alvo, preco_stop
    global operacoes_realizadas, lucro_total, relatorio_operacoes

    data = request.get_json()

    if 'message' not in data:
        return {"ok": True}

    mensagem = data['message']
    texto = mensagem.get("text", "")

    if texto == "/status":
        if operacao_ativa:
            lucro_ou_prejuizo = (preco_atual() - preco_entrada) / preco_entrada
            if tipo_operacao == 'short':
                lucro_ou_prejuizo *= -1
            lucro_real = lucro_ou_prejuizo * 20 * 100
            enviar_mensagem(f"📊 Operação ativa ({tipo_operacao.upper()})\nEntrada: {preco_entrada:.2f}\nAlvo: {preco_alvo:.2f}\nStop: {preco_stop:.2f}\nLucro atual: {lucro_real:.2f}%")
        else:
            enviar_mensagem("🚫 Nenhuma operação ativa.")

    elif texto == "/statusdia":
        enviar_mensagem(f"🗓️ Relatório:\nTotal: {operacoes_realizadas} operações\nLucro: {lucro_total:.2f}%\nÚltimas:\n" + "\n".join(relatorio_operacoes[-10:]))

    return {"ok": True}

@app.route("/")
def home():
    return "Bot ativo"

# ============ TAREFA EM BACKGROUND ============

def loop_operacoes():
    global operacao_ativa, tipo_operacao, preco_entrada, preco_alvo, preco_stop
    global operacoes_realizadas, lucro_total, relatorio_operacoes, tempo_ultima_operacao

    while True:
        try:
            df = pegar_dados()
            df = analisar(df)
            preco = df['close'].iloc[-1]

            if operacao_ativa:
                if tipo_operacao == 'long':
                    if preco >= preco_alvo:
                        lucro = 10.0
                        enviar_mensagem(f"✅ Alvo atingido! Lucro de {lucro:.2f}%\nPreço: {preco:.2f}")
                    elif preco <= preco_stop:
                        lucro = -10.0
                        enviar_mensagem(f"❌ Stop atingido! Prejuízo de {lucro:.2f}%\nPreço: {preco:.2f}")
                    else:
                        time.sleep(10)
                        continue
                elif tipo_operacao == 'short':
                    if preco <= preco_alvo:
                        lucro = 10.0
                        enviar_mensagem(f"✅ Alvo SHORT! Lucro de {lucro:.2f}%\nPreço: {preco:.2f}")
                    elif preco >= preco_stop:
                        lucro = -10.0
                        enviar_mensagem(f"❌ Stop SHORT! Prejuízo de {lucro:.2f}%\nPreço: {preco:.2f}")
                    else:
                        time.sleep(10)
                        continue
                else:
                    time.sleep(10)
                    continue

                operacao_ativa = False
                tempo_ultima_operacao = time.time()
                operacoes_realizadas += 1
                lucro_total += lucro
                relatorio_operacoes.append(f"{tipo_operacao.upper()} | Lucro: {lucro:.2f}%")

            else:
                if time.time() - tempo_ultima_operacao < 60 or operacoes_realizadas >= 10:
                    time.sleep(10)
                    continue

                ema9 = df['EMA9'].iloc[-1]
                ema21 = df['EMA21'].iloc[-1]
                rsi = df['RSI6'].iloc[-1]
                macd = df['MACD'].iloc[-1]
                signal = df['Signal'].iloc[-1]

                if ema9 > ema21 and rsi > 55 and macd > signal:
                    tipo_operacao = 'long'
                    preco_entrada = preco
                    preco_alvo = preco * (1 + lucro_desejado)
                    preco_stop = preco * (1 - perda_maxima)
                    operacao_ativa = True
                    enviar_mensagem(f"📈 COMPRA - Entrada: {preco:.2f}\nAlvo: {preco_alvo:.2f}\nStop: {preco_stop:.2f}")

                elif ema9 < ema21 and rsi < 45 and macd < signal:
                    tipo_operacao = 'short'
                    preco_entrada = preco
                    preco_alvo = preco * (1 - lucro_desejado)
                    preco_stop = preco * (1 + perda_maxima)
                    operacao_ativa = True
                    enviar_mensagem(f"📉 SHORT - Entrada: {preco:.2f}\nAlvo: {preco_alvo:.2f}\nStop: {preco_stop:.2f}")

            time.sleep(10)
        except Exception as e:
            print("Erro no loop:", e)
            time.sleep(10)

# Iniciar thread paralela para o loop
threading.Thread(target=loop_operacoes, daemon=True).start()

# Iniciar o servidor Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
