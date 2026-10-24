from datetime import datetime
import re
import pdfplumber
import streamlit as st

# 페이지 설정
st.set_page_config(
    page_title="공항 NOTAM 비교 및 분석기", page_icon="✈️", layout="wide"
)

SECTIONS = [
    "COMPANY ADVISORY",
    "RUNWAY",
    "TAXIWAY",
    "RAMP",
    "DEPARTURE",
    "APPROACH",
    "AIRPORT",
    "GPS",
]


def extract_text_from_pdf(pdf_file):
  text = []
  with pdfplumber.open(pdf_file) as pdf:
    for page in pdf.pages:
      extracted = page.extract_text()
      if extracted:
        text.append(extracted)
  return "\n".join(text)


def normalize_body(body_text):
  lines = body_text.splitlines()
  content_lines = lines[1:] if len(lines) > 1 else lines
  return " ".join(" ".join(content_lines).split()).upper()


def parse_notam_blocks(text):
  lines = text.splitlines()
  current_section = "OTHER"
  notams = {}
  notam_pattern = r"([A-Z]{4}\s+[A-Z]\d{4}/\d{2})"

  current_notam = None
  current_airport = None
  current_text = []
  b_time = None
  c_time = None

  for line in lines:
    stripped_line = line.strip()
    upper_line = stripped_line.upper()

    matched_sec = None
    if len(upper_line) < 35:
      cleaned_header = re.sub(r"[\:\-\–\d\.\s]", "", upper_line)
      for sec in SECTIONS:
        if cleaned_header == sec.replace(" ", ""):
          matched_sec = sec
          break

    if matched_sec:
      current_section = matched_sec
      continue

    match = re.search(notam_pattern, line)
    if match:
      if current_notam:
        body_str = "\n".join(current_text)
        notams[current_notam] = {
            "airport": current_airport,
            "section": current_section,
            "b_time": b_time,
            "c_time": c_time,
            "body": body_str,
            "norm_body": normalize_body(body_str),
        }
      full_notam = match.group(1)
      parts = full_notam.split()
      current_airport = parts[0]
      current_notam = full_notam
      current_text = [line]
      b_time = None
      c_time = None
    elif current_notam:
      current_text.append(line)
      if "B)" in upper_line or "FROM" in upper_line:
        time_match = re.search(r"(\d{10})", line)
        if time_match:
          b_time = time_match.group(1)
      if "C)" in upper_line or "TO" in upper_line:
        if "PERM" in upper_line:
          c_time = "PERM"
        else:
          time_match = re.search(r"(\d{10})", line)
          if time_match:
            c_time = time_match.group(1)

  if current_notam:
    body_str = "\n".join(current_text)
    notams[current_notam] = {
        "airport": current_airport,
        "section": current_section,
        "b_time": b_time,
        "c_time": c_time,
        "body": body_str,
        "norm_body": normalize_body(body_str),
      }

  return notams


def parse_datetime_input(date_str):
  date_str = date_str.strip()
  formats = ["%y%m%d%H%M", "%Y-%m-%d %H:%M", "%y-%m-%d %H:%M"]
  for fmt in formats:
    try:
      return datetime.strptime(date_str, fmt)
    except ValueError:
      continue
  return None


def is_affecting_flight(b_time_str, c_time_str, flight_start, flight_end):
  if not b_time_str:
    return True
  try:
    notam_start = datetime.strptime(b_time_str, "%y%m%d%H%M")
    if c_time_str == "PERM":
      notam_end = datetime(2099, 12, 31, 23, 59)
    elif c_time_str:
      notam_end = datetime.strptime(c_time_str, "%y%m%d%H%M")
    else:
      notam_end = datetime(2099, 12, 31, 23, 59)

    if notam_start <= flight_end and notam_end >= flight_start:
      return True
  except Exception:
    pass
  return False


# --- 웹 UI 구성 ---
st.title("✈️ 공항 NOTAM 비교 및 운항 영향 분석기")
st.write(
    "이전 발행본(Old PDF)과 최신 발행본(New PDF)을 비교하여, 새로 추가된"
    " NOTAM과 비행 시간 영향 여부를 분석합니다."
)

st.sidebar.header("📂 파일 업로드 및 설정")
old_file = st.sidebar.file_uploader("이전 NOTAM PDF (Old)", type=["pdf"])
new_file = st.sidebar.file_uploader("최신 NOTAM PDF (New)", type=["pdf"])

st.sidebar.markdown("---")
st.sidebar.header("⏰ 운항 시간 설정 (선택)")
flight_date = st.sidebar.date_input("비행 날짜")
start_time_str = st.sidebar.text_input("출발 시간 (HHMM)", "0800")
end_time_str = st.sidebar.text_input("도착 시간 (HHMM)", "1400")

# 날짜와 시간을 합쳐서 datetime 객체 생성
flight_start, flight_end = None, None
try:
  if flight_date and start_time_str and end_time_str:
    start_dt_str = (
        f"{flight_date.strftime('%y%m%d')}{start_time_str.strip()}"
    )
    end_dt_str = f"{flight_date.strftime('%y%m%d')}{end_time_str.strip()}"
    flight_start = datetime.strptime(start_dt_str, "%y%m%d%H%M")
    flight_end = datetime.strptime(end_dt_str, "%y%m%d%H%M")
except Exception:
  st.sidebar.warning(
      "시간 형식이 올바르지 않습니다. (예시: 0800 입력)"
  )

if st.sidebar.button("🚀 분석 실행하기", type="primary"):
  if not old_file or not new_file:
    st.error("⚠️ Old PDF와 New PDF 파일을 모두 업로드해 주세요!")
  else:
    with st.spinner("NOTAM 분석 중입니다... 잠시만 기다려주세요!"):
      text1 = extract_text_from_pdf(old_file)
      text2 = extract_text_from_pdf(new_file)

      notams1 = parse_notam_blocks(text1)
      notams2 = parse_notam_blocks(text2)

      old_body_map = {}
      for o_num, o_data in notams1.items():
        nb = o_data["norm_body"]
        if nb not in old_body_map:
          old_body_map[nb] = []
        old_body_map[nb].append(o_num)

      added_set = set(notams2.keys()) - set(notams1.keys())
      ordered_added_keys = [k for k in notams2.keys() if k in added_set]

      if not ordered_added_keys:
        st.success("🎉 새로 추가된 NOTAM이 없습니다!")
      else:
        structured_output = {}
        for key in ordered_added_keys:
          data = notams2[key]
          airport = data["airport"] or "UNKNOWN"
          section = data["section"]
          nb = data["norm_body"]

          if airport not in structured_output:
            structured_output[airport] = {}
          if section not in structured_output[airport]:
            structured_output[airport][section] = []

          matched_old_numbers = old_body_map.get(nb, [])
          affecting = False
          if flight_start and flight_end:
            affecting = is_affecting_flight(
                data["b_time"], data["c_time"], flight_start, flight_end
            )

          structured_output[airport][section].append(
              (key, matched_old_numbers, affecting, data["body"])
          )

        st.success(
            f"✅ 분석 완료! 총 {len(ordered_added_keys)}개의 신규/변경"
            " NOTAM을 발견했습니다."
        )

        for airport in sorted(structured_output.keys()):
          st.markdown(f"## ✈️ 공항: {airport}")
          for section in SECTIONS + ["OTHER"]:
            if section in structured_output[airport]:
              items = structured_output[airport][section]
              st.markdown(f"### 📂 [{section}]")

              for notam_num, matched_old, affecting, body in items:
                if matched_old:
                  old_str = ", ".join(matched_old)
                  st.info(
                      f"**🔄 [내용 동일 / 번호 변경] (구 번호: {old_str})**"
                      f" `{notam_num}`"
                  )
                else:
                  if affecting and flight_start:
                    st.error(
                        f"**🚨 [완전 신규 / 영향 있음]** `{notam_num}`"
                    )
                  else:
                    st.warning(f"**➕ [완전 신규 (참고)]** `{notam_num}`")

                st.code(body, language="text")
