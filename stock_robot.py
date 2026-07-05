import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import ta

# ---------------------------------------------------------------------------
# [환경 설정] (OpenAI 제거 완료, 완전 무료화)
# ---------------------------------------------------------------------------
# 텔레그램 봇 설정 (GitHub Secrets 연동)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
}

# ---------------------------------------------------------------------------
# [1단계: 네이버 증권에서 인기(거래량/급등) 상위 100개 종목 긁어오기]
# ---------------------------------------------------------------------------
def get_top_100_stocks():
    print("🔄 1단계: 실시간 변동성 및 거래량 상위 100개 종목 수집 중...")
    stocks = []
    
    urls = [
        "https://finance.naver.com/sise/sise_quant.naver", # 거래상위
        "https://finance.naver.com/sise/sise_rise.naver"   # 급등
    ]
    
    for url in urls:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for a_tag in soup.find_all('a', class_='tltle'):
            code = a_tag['href'].split('code=')[-1]
            name = a_tag.text.strip()
            if {"code": code, "name": name} not in stocks:
                stocks.append({"code": code, "name": name})
            if len(stocks) >= 100:
                break
        if len(stocks) >= 100:
            break
            
    return stocks[:100]

# ---------------------------------------------------------------------------
# [2단계: 기술적 지표 분석 - 상승 돌파(Momentum) 시그널 포착 알고리즘]
# ---------------------------------------------------------------------------
def analyze_chart_trend(stock_code):
    """
    네이버 일봉 데이터를 가져와 이동평균선, MACD, 거래량 급증 여부를 수학적으로 판별
    """
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={stock_code}&timeframe=day&count=60&requestType=0"
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'xml')
    
    items = soup.find_all('item')
    if not items:
        return False, 0, ""
        
    data_close = []
    data_vol = []
    for item in items:
        # 데이터 포맷: 날짜|시가|고가|저가|종가|거래량
        values = item['data'].split('|')
        data_close.append(float(values[4])) # 종가
        data_vol.append(float(values[5]))   # 거래량
        
    df = pd.DataFrame({'close': data_close, 'volume': data_vol})
    
    if len(df) < 30:
        return False, 0, ""
        
    # --- 기술적 지표 계산 ---
    # 1. 이동평균선 (5일선, 20일선)
    df['ma5'] = ta.trend.sma_indicator(df['close'], window=5)
    df['ma20'] = ta.trend.sma_indicator(df['close'], window=20)
    
    # 2. MACD 지표
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    
    # 3. 거래량 이동평균 (20일 평균)
    df['vol_ma20'] = df['volume'].rolling(window=20).mean()
    
    current_price = df['close'].iloc[-1]
    
    # --- 💡 상승 시그널 판별 (어제와 오늘의 지표 변화 비교) ---
    
    # 조건 1: 🌟 골든크로스 (5일선이 20일선을 상향 돌파했는가?)
    is_golden_cross = (df['ma5'].iloc[-2] <= df['ma20'].iloc[-2]) and (df['ma5'].iloc[-1] > df['ma20'].iloc[-1])
    
    # 조건 2: 📈 MACD 매수 시그널 (MACD가 시그널 선을 상향 돌파했는가?)
    is_macd_cross = (df['macd'].iloc[-2] <= df['macd_signal'].iloc[-2]) and (df['macd'].iloc[-1] > df['macd_signal'].iloc[-1])
    
    # 조건 3: 🔥 거래량 급증 (오늘 거래량이 20일 평균 거래량보다 200% 이상 많은가?)
    is_vol_surge = df['volume'].iloc[-1] > (df['vol_ma20'].iloc[-2] * 2)
    
    # 시그널 요약 텍스트 생성
    reasons = []
    if is_golden_cross: reasons.append("🌟 5일/20일 골든크로스 발생")
    if is_macd_cross: reasons.append("📈 MACD 상향 돌파 (매수 시그널)")
    if is_vol_surge: reasons.append("🔥 최근 평균 대비 거래량 2배 이상 터짐")
    
    # 세 가지 조건 중 2가지 이상이 동시에 발생하면 상승 확률이 매우 높은 것으로 판단
    score = sum([is_golden_cross, is_macd_cross, is_vol_surge])
    
    if score >= 2:
        return True, current_price, "\n- ".join(reasons)
        
    return False, current_price, ""

# ---------------------------------------------------------------------------
# [3단계: 텔레그램 알림 발송]
# ---------------------------------------------------------------------------
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 텔레그램 토큰이 설정되지 않아 화면에만 출력합니다:\n", message)
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    res = requests.post(url, json=payload)
    
    if res.status_code != 200:
        print("❌ 텔레그램 발송 실패:", res.json())

# ---------------------------------------------------------------------------
# [메인 실행 제어 프로세스]
# ---------------------------------------------------------------------------
def main():
    print("🚀 주식 상승 돌파(Momentum) 포착 프로그램 가동 🚀")
    top_100 = get_top_100_stocks()
    
    candidates = []
    print(f"🔍 2단계: {len(top_100)}개 종목 추세 분석 시작...")
    
    final_report = "🚨 **금일 주식 상승 돌파 포착 리스트** 🚨\n\n"
    valid_count = 0
    
    for stock in top_100:
        is_uptrend, price, reason_text = analyze_chart_trend(stock['code'])
        if is_uptrend:
            print(f"✨ 시그널 발견: {stock['name']} ({price}원)")
            final_report += f"■ **종목명**: {stock['name']} ({stock['code']})\n"
            final_report += f"- **현재가**: {int(price):,}원\n"
            final_report += f"- {reason_text}\n"
            final_report += "--------------------------------------\n"
            valid_count += 1
            
    # 결과 전송 로직
    if valid_count > 0:
        send_telegram_message(final_report)
        print("✅ 분석 완료! 결과를 텔레그램으로 전송했습니다.")
    else:
        empty_message = "📭 **오늘의 주식 분석 결과**\n\n현재 시장(상위 100종목)에서 확실한 상승 돌파 시그널(골든크로스, MACD, 거래량 급증 등)이 2개 이상 겹친 종목이 발견되지 않았습니다. 내일 다시 탐색합니다."
        send_telegram_message(empty_message)
        print("📭 종목이 없어 빈 결과 알림을 텔레그램으로 전송했습니다.")

if __name__ == "__main__":
    main()
