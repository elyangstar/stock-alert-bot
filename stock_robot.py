import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import ta
from openai import OpenAI

# ---------------------------------------------------------------------------
# [환경 설정 및 API 키] (GitHub Secrets 연동 완료)
# ---------------------------------------------------------------------------
# OpenAI API 키 설정
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# 텔레그램 봇 설정 
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
# [2단계: 기술적 지표 분석 - 반등 시그널 포착 알고리즘]
# ---------------------------------------------------------------------------
def analyze_chart_rebound(stock_code):
    """
    네이버 일봉 데이터를 가져와 RSI 과매도 구간 탈출 및 볼린저 밴드 하단 지지 여부 판별
    """
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={stock_code}&timeframe=day&count=60&requestType=0"
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'xml') # lxml 파서 사용
    
    items = soup.find_all('item')
    if not items:
        return False, 0
        
    data = []
    for item in items:
        values = item['data'].split('|')
        data.append(float(values[4]))
        
    df = pd.DataFrame(data, columns=['close'])
    
    if len(df) < 30:
        return False, 0
        
    # 기술적 지표 계산 (ta 라이브러리 활용, window_dev 에러 수정 완료)
    rsi = ta.momentum.rsi(df['close'], window=14)
    bb_low = ta.volatility.bollinger_lband(df['close'], window=20, window_dev=2)
    
    current_price = df['close'].iloc[-1]
    current_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2]
    current_bb_low = bb_low.iloc[-1]
    
    # 💡 반등 시그널 조건 정의 (조건 완화 적용 완료)
    is_rsi_rebound = (prev_rsi <= 50) and (current_rsi > prev_rsi)
    is_bb_support = current_price <= current_bb_low * 1.10
    
    if is_rsi_rebound or is_bb_support:
        return True, current_price
        
    return False, current_price

# ---------------------------------------------------------------------------
# [3단계: 네이버 뉴스 크롤링 및 AI 분석]
# ---------------------------------------------------------------------------
def get_stock_news(stock_name):
    """ 종목명 기반 최신 뉴스 5개 수집 """
    url = f"https://search.naver.com/search.naver?where=news&query={stock_name}"
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    news_titles = []
    for title in soup.find_all('a', class_='news_tit'):
        news_titles.append(title.text.strip())
        if len(news_titles) >= 5:
            break
            
    return "\n".join(news_titles)

def ai_analyze_rebound_potential(stock_name, current_price, news_text):
    """ OpenAI GPT를 이용해 호재 여부 판별 및 상승률 추정 """
    if not client:
        return f"💡 {stock_name} 차트 반등 시그널 포착 완료. (AI 뉴스 분석은 API 키 필요)"

    prompt = f"""
    당신은 전문 주식 분석가입니다. 
    종목 [{stock_name}]의 현재가는 {current_price}원이며, 최근 수집된 뉴스 헤드라인은 다음과 같습니다:
    
    {news_text}
    
    이 뉴스를 기반으로 해당 종목이 하반기에 반등할 수 있는 '실질적인 호재(수주, 실적 흑자전환, 신제품)'가 있는지 분석하세요.
    만약 단순 작전성 테마나 악재라면 과감히 제외하세요.
    조건에 부합한다면 다음 포맷으로만 답변하세요:
    [호재 요약] <1줄 요약>
    [예상 상승률] <증권가 목표가나 매물대 기반 추정 % 범위>
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        return response.choices[0].message.content
    except Exception as e:
        return "⚠️ AI 분석 중 오류가 발생했습니다."

# ---------------------------------------------------------------------------
# [4단계: 텔레그램 알림 발송]
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
    print("🚀 주식 반등 신호 포착 프로그램 가동 🚀")
    top_100 = get_top_100_stocks()
    
    candidates = []
    print(f"🔍 2단계: {len(top_100)}개 종목 차트 분석 시작...")
    
    for stock in top_100:
        is_rebound, price = analyze_chart_rebound(stock['code'])
        if is_rebound:
            print(f"✨ 시그널 발견: {stock['name']} ({price}원)")
            candidates.append({"code": stock['code'], "name": stock['name'], "price": price})
            
    print(f"\n📰 3단계: 포착된 {len(candidates)}개 종목 뉴스 스크리닝 및 AI 검증...")
    final_report = "🚨 **금일 주식 반등 신호 포착 리스트** 🚨\n\n"
    
    valid_count = 0
    for cand in candidates:
        news = get_stock_news(cand['name'])
        if not news:
            continue
            
        ai_analysis = ai_analyze_rebound_potential(cand['name'], cand['price'], news)
        
        # 단순 악재 주식 거르기
        if "제외" in ai_analysis or "악재" in ai_analysis:
            continue
            
        final_report += f"■ **종목명**: {cand['name']} ({cand['code']})\n"
        final_report += f"- **현재가**: {int(cand['price'])}원\n"
        final_report += f"{ai_analysis}\n"
        final_report += "--------------------------------------\n"
        valid_count += 1
        
    # 결과가 있든 없든 무조건 알림 전송 (수정 완료)
    if valid_count > 0:
        send_telegram_message(final_report)
        print("✅ 분석 완료! 결과를 텔레그램으로 전송했습니다.")
    else:
        empty_message = "📭 **오늘의 주식 분석 결과**\n\n현재 시장(상위 100종목)에서 차트 바닥 조건 및 AI 호재 검증을 모두 통과한 안전한 종목이 발견되지 않았습니다. 내일 다시 탐색합니다."
        send_telegram_message(empty_message)
        print("📭 종목이 없어 빈 결과 알림을 텔레그램으로 전송했습니다.")

if __name__ == "__main__":
    main()