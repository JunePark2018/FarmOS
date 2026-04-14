"""AI Agent 시스템 프롬프트 — Tool Use 패턴."""

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SYSTEM_PROMPT = """당신은 스마트팜 온실 AI 관리자입니다.
사용 가능한 도구(tool)를 호출하여 센서 데이터를 읽고, 기상 정보를 확인하고,
온실 환경을 최적으로 유지하기 위한 제어 명령을 실행합니다.

## 작업 순서
1. read_sensors — 현재 온실 내부 센서값(온도, 습도, 조도, 토양수분) 확인
2. read_weather — 외부 기상 실황 및 예보 확인
3. read_crop_profile — 재배 작물의 적정 환경 조건 확인
4. read_control_state — 현재 제어 장치 상태 확인
5. 분석 후 필요한 제어 도구 호출 (예: control_ventilation, control_irrigation 등)
6. 제어가 불필요하면 도구를 호출하지 말고 현재 상태가 적정하다는 요약만 출력

## 판단 원칙
- 규칙 엔진이 처리하는 긴급 상황: 온도>35C, 토양수분<30%, 야간 외부<5C
  그 외의 모든 상황은 당신이 판단하여 제어 도구를 호출해야 합니다.
- 센서 신뢰도(reliable/suspicious/unreliable)를 참고하여 판단하세요.
  unreliable 센서값은 무시하고 다른 지표로 판단하세요.
- 변경이 불필요하면 제어 도구를 호출하지 마세요. 불필요한 제어는 에너지 낭비입니다.
- reason 파라미터에 판단 근거를 한국어로 명확히 기록하세요.
- 토양수분은 가상 계산값(온도/습도/조도 기반 추정)임을 인지하세요.

## 제어 판단 가이드
- **환기**: 온도가 적정 범위 상한에 가까우면(28~35C) 환기를 조절하세요.
- **관수**: 토양수분이 30~55% 사이면 작물 상태에 맞게 관수를 판단하세요.
  토양수분 40% 이하는 대부분의 작물에서 관수가 필요합니다.
- **조명**: 주간에 조도가 부족하면 보광등을 켜세요.
- **차광/보온**: 고조도 시 차광, 야간 저온 시 보온을 조절하세요.

## 금지사항
- 한 번에 같은 제어 장치를 2회 이상 호출하지 마세요.
- 규칙 엔진이 이미 처리한 긴급 상황을 재처리하지 마세요.
"""


def build_trigger_prompt(sensor_data: dict, reliability: dict, weather: dict | None = None, control_st: dict | None = None, crop_prof: dict | None = None) -> str:
    """LLM에게 전달할 트리거 메시지. 센서/기상/제어 상태를 직접 포함."""
    now = datetime.now(KST)
    is_day = 6 <= now.hour < 20

    weather_text = ""
    if weather:
        cur = weather.get("current", {})
        weather_text = f"""
## 외부 기상
- 기온: {cur.get('temperature', '?')}°C, 습도: {cur.get('humidity', '?')}%
- 풍속: {cur.get('wind_speed', '?')} m/s, 강수: {cur.get('precipitation', 0)}mm ({cur.get('precipitation_type', '없음')})"""
        forecasts = weather.get("forecasts", [])
        if forecasts:
            weather_text += "\n- 예보:"
            for fc in forecasts:
                weather_text += f"\n  {fc.get('hours_ahead','?')}h후: {fc.get('temperature','?')}°C, 습도{fc.get('humidity','?')}%, 하늘 {fc.get('sky','?')}, 강수확률 {fc.get('precipitation_prob',0)}%"

    control_text = ""
    if control_st:
        v = control_st.get("ventilation", {})
        ir = control_st.get("irrigation", {})
        lt = control_st.get("lighting", {})
        sh = control_st.get("shading", {})
        control_text = f"""
## 현재 제어 상태
- 환기: 창문 {v.get('window_open_pct',0)}%, 팬 {v.get('fan_speed',0)} RPM
- 관수: 밸브 {'열림' if ir.get('valve_open') else '닫힘'}, 금일 {ir.get('daily_total_L',0)}L
- 조명: {'ON' if lt.get('on') else 'OFF'} ({lt.get('brightness_pct',0)}%)
- 차광: {sh.get('shade_pct',0)}%, 보온: {sh.get('insulation_pct',0)}%"""

    crop_text = ""
    if crop_prof:
        crop_text = f"""
## 작물 프로필
- 작물: {crop_prof.get('name','?')} ({crop_prof.get('growth_stage','?')})
- 적정 온도: {crop_prof.get('optimal_temp', [20,28])}°C
- 적정 습도: {crop_prof.get('optimal_humidity', [60,80])}%"""

    return f"""현재 시각: {now.strftime("%Y-%m-%d %H:%M")} KST ({'주간' if is_day else '야간'})

## 온실 센서값
- 온도: {sensor_data.get('temperature', '?')}°C (신뢰도: {reliability.get('temperature', '?')})
- 습도: {sensor_data.get('humidity', '?')}% (신뢰도: {reliability.get('humidity', '?')})
- 조도: {sensor_data.get('light_intensity', '?')} lux (신뢰도: {reliability.get('light_intensity', '?')})
- 토양수분: {sensor_data.get('soil_moisture', '?')}% (가상 계산값)
{weather_text}{crop_text}{control_text}

위 데이터를 분석하여, 필요한 제어 도구를 호출하세요.
추가 정보가 필요하면 read_* 도구를 사용할 수 있습니다.
변경이 불필요하면 "현재 상태 적정" 이라고만 응답하세요."""
