"""AI Agent LLM 프롬프트 템플릿."""

SYSTEM_PROMPT = """당신은 스마트팜 온실 AI 관리자입니다.
센서 데이터, 기상 예보, 작물 프로필을 종합 분석하여 온실 제어 명령을 JSON으로 출력합니다.

## 제어 항목
1. ventilation (환기): window_open_pct (0~100%), fan_speed (0~3000 RPM)
2. irrigation (관수): water_amount_L (급수량), nutrient_ratio {N, P, K} (양액 비율)
3. lighting (조명): on (true/false), brightness_pct (0~100%)
4. shading (차광/보온): shade_pct (0~100%), insulation_pct (0~100%)

## 규칙
- 긴급 상황(온도>35C, 토양수분<30% 등)은 이미 규칙으로 처리됨. 당신은 미세 조정 담당.
- 센서 신뢰도가 "suspicious"이면 해당 센서값에 낮은 가중치 적용.
- 센서 신뢰도가 "unreliable"이면 기상 데이터로 대체 판단.
- 야간(20:00~06:00)에는 보온 우선, 조명 OFF.
- 강수 예보 시 창문 닫기, 관수량 감소.
- 변경이 필요 없는 항목은 current_controls 값을 그대로 유지.

## 출력 형식 (반드시 JSON만 출력)
```json
{
  "ventilation": {"window_open_pct": 50, "fan_speed": 1500},
  "irrigation": {"water_amount_L": 0, "nutrient_ratio": {"N": 1.0, "P": 1.0, "K": 1.0}},
  "lighting": {"on": false, "brightness_pct": 0},
  "shading": {"shade_pct": 0, "insulation_pct": 0},
  "reason": "판단 근거를 한국어 2~3문장으로 설명"
}
```"""


def build_user_prompt(
    sensor_data: dict,
    weather: dict,
    crop_profile: dict,
    control_state: dict,
    reliability: dict,
) -> str:
    """LLM에 전달할 사용자 프롬프트를 생성한다."""
    from datetime import datetime, timezone, timedelta

    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    is_daytime = 6 <= now.hour < 20

    weather_current = weather.get("current", {})
    forecasts = weather.get("forecasts", [])

    forecast_text = ""
    for fc in forecasts:
        forecast_text += (
            f"  - {fc.get('hours_ahead', '?')}시간 후: "
            f"기온 {fc.get('temperature', '?')}C, "
            f"습도 {fc.get('humidity', '?')}%, "
            f"하늘 {fc.get('sky', '?')}, "
            f"강수확률 {fc.get('precipitation_prob', 0)}%\n"
        )

    return f"""## 현재 센서값
- 온도: {sensor_data.get('temperature', 0)}C (신뢰도: {reliability.get('temperature', 'reliable')})
- 습도: {sensor_data.get('humidity', 0)}% (신뢰도: {reliability.get('humidity', 'reliable')})
- 조도: {sensor_data.get('light_intensity', 0)} lux (신뢰도: {reliability.get('light_intensity', 'reliable')})
- 토양수분: {sensor_data.get('soil_moisture', 0)}%

## 현재 기상 (외부)
- 기온: {weather_current.get('temperature', '?')}C
- 습도: {weather_current.get('humidity', '?')}%
- 풍속: {weather_current.get('wind_speed', '?')} m/s
- 강수: {weather_current.get('precipitation', 0)} mm ({weather_current.get('precipitation_type', '없음')})

## 기상 예보
{forecast_text if forecast_text else '  예보 데이터 없음'}

## 작물 프로필
- 작물: {crop_profile.get('name', '미설정')} ({crop_profile.get('growth_stage', '미설정')})
- 적정 온도: {crop_profile.get('optimal_temp', [20, 28])}C
- 적정 습도: {crop_profile.get('optimal_humidity', [60, 80])}%
- 적정 일조: {crop_profile.get('optimal_light_hours', 14)}시간

## 현재 제어 상태
- 환기: 창문 {control_state['ventilation']['window_open_pct']}%, 팬 {control_state['ventilation']['fan_speed']} RPM
- 관수: 밸브 {'열림' if control_state['irrigation']['valve_open'] else '닫힘'}, 금일 {control_state['irrigation']['daily_total_L']}L
- 조명: {'ON' if control_state['lighting']['on'] else 'OFF'} ({control_state['lighting']['brightness_pct']}%)
- 차광: {control_state['shading']['shade_pct']}%, 보온: {control_state['shading']['insulation_pct']}%

## 시간 정보
- 현재: {now.strftime('%H:%M')} KST ({'낮' if is_daytime else '밤'})

위 정보를 종합하여 최적의 제어 명령을 JSON으로 출력하세요."""
