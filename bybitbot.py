import time
import requests
import pandas as pd
from binance.client import Client
from datetime import datetime

# Configuração Telegram
BOT_TOKEN = '7723343194:AAEpgCrA6mymE5VeSv2DDdQ6sAVvVMJvCYc'
CHAT_ID = '948274284'

client = Client()

# Estado da operação
operacao_ativa = False
tipo_operacao = None  # 'long' ou 'short'
preco_entrada = 0.0
preco_alvo = 0.0
preco_stop = 0.0
operacoes_realizadas = 0
lucro_total = 0.0
relatorio_operacoes = []
ultima_resposta_status = 0
ultima_resposta_statusdia = 0
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
    candles = client.get_klines(symbol="DOGEUSDT", interval=Client.KLINE_INTERVAL_5MINUTE, limit=50)
    df = pd.DataFrame(candles, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
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


def verificar_comandos():
    global ultima_resposta_status, ultima_resposta_statusdia
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/getUpdates'
    res = requests.get(url).json()
    if not res.get("result"):
        return

    mensagem = res["result"][-1]["message"]
    texto = mensagem.get("text", "")
    data_msg = mensagem["date"]

    if texto == "/status" and data_msg > ultima_resposta_status:
        ultima_resposta_status = data_msg
        if operacao_ativa:
            lucro_ou_prejuizo = (preco_atual() - preco_entrada) / preco_entrada
            if tipo_operacao == 'short':
                lucro_ou_prejuizo *= -1
            lucro_real = lucro_ou_prejuizo * 20 * 100
            enviar_mensagem(f"📊 Operação ativa ({tipo_operacao.upper()})\nEntrada: {preco_entrada:.2f}\nAlvo: {preco_alvo:.2f}\nStop: {preco_stop:.2f}\nLucro atual: {lucro_real:.2f}%")
        else:
            enviar_mensagem("🚫 Nenhuma operação ativa no momento.")

    if texto == "/statusdia" and data_msg > ultima_resposta_statusdia:
        ultima_resposta_statusdia = data_msg
        enviar_mensagem(f"🗓️ Relatório do dia:\nTotal: {operacoes_realizadas} operações\nLucro acumulado: {lucro_total:.2f}%\nDetalhes:\n" + "\n".join(relatorio_operacoes[-10:]))


def preco_atual():
    df = pegar_dados()
    return df['close'].iloc[-1]


def checar_saida(preco):
    global operacao_ativa, tipo_operacao, preco_entrada, preco_alvo, preco_stop
    global operacoes_realizadas, lucro_total, relatorio_operacoes, tempo_ultima_operacao

    if tipo_operacao == 'long':
        if preco >= preco_alvo:
            lucro = 10.0
            enviar_mensagem(f"✅ Alvo atingido! Lucro de {lucro:.2f}%\nPreço: {preco:.2f}")
        elif preco <= preco_stop:
            lucro = -10.0
            enviar_mensagem(f"❌ Stop atingido! Prejuízo de {lucro:.2f}%\nPreço: {preco:.2f}")
        else:
            return
    elif tipo_operacao == 'short':
        if preco <= preco_alvo:
            lucro = 10.0
            enviar_mensagem(f"✅ Alvo do SHORT atingido! Lucro de {lucro:.2f}%\nPreço: {preco:.2f}")
        elif preco >= preco_stop:
            lucro = -10.0
            enviar_mensagem(f"❌ Stop do SHORT atingido! Prejuízo de {lucro:.2f}%\nPreço: {preco:.2f}")
        else:
            return
    else:
        return

    operacao_ativa = False
    tempo_ultima_operacao = time.time()
    operacoes_realizadas += 1
    lucro_total += lucro
    relatorio_operacoes.append(f"{tipo_operacao.upper()} | Lucro: {lucro:.2f}%")


def executar_operacao(df):
    global operacao_ativa, tipo_operacao, preco_entrada, preco_alvo, preco_stop

    if operacao_ativa or operacoes_realizadas >= 10:
        return

    if time.time() - tempo_ultima_operacao < 60:
        return

    preco = df['close'].iloc[-1]
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
        enviar_mensagem(f"📈 COMPRA - Entrada: {preco:.2f}\n🌟 Alvo: {preco_alvo:.2f}\n🚩 Stop: {preco_stop:.2f}")

    elif ema9 < ema21 and rsi < 45 and macd < signal:
        tipo_operacao = 'short'
        preco_entrada = preco
        preco_alvo = preco * (1 - lucro_desejado)
        preco_stop = preco * (1 + perda_maxima)
        operacao_ativa = True
        enviar_mensagem(f"📉 VENDA - Entrada (SHORT): {preco:.2f}\n🌟 Alvo: {preco_alvo:.2f}\n🚩 Stop: {preco_stop:.2f}")


# Loop principal
while True:
    try:
        verificar_comandos()
        df = pegar_dados()
        df = analisar(df)

        if operacao_ativa:
            checar_saida(df['close'].iloc[-1])
        else:
            executar_operacao(df)

        time.sleep(10)
    except Exception as e:
        print("Erro:", e)
        time.sleep(10)
