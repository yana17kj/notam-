from datetime import datetime
import re
import pdfplumber

# 분류할 항목(섹션) 리스트
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


def extract_text_from_pdf(pdf_path):
  """PDF 파일에서 텍스트를 추출하는 함수"""
  text = []
  with pdfplumber.open(pdf_path) as pdf:
    for page in pdf.pages:
      extracted = page.extract_text()
      if extracted:
        text.append(extracted)
  return "\n".join(text)


def normalize_body(body_text):
  """NOTAM 본문에서 순수 내용만 비교할 수 있게 정규화"""
  lines = body_text.splitlines()
  if len(lines) > 1:
    content_lines = lines[1:]
  else:
    content_lines = lines
  normalized = " ".join(" ".join(content_lines).split())
  return normalized.upper()


def parse_notam_blocks(text):
  """텍스트에서 각 NOTAM의 상세 정보를 강력하게 정제된 섹션 기준으로 파싱하는 함수"""
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

    # [핵심 보완] 콜론(:), 대시(-), 숫자, 공백 등이 섞여 있어도 섹션 이름을 정확히 감지
    matched_sec = None
    if len(upper_line) < 35:  # 섹션 제목은 보통 짧은 단독 라인임
      # 특수문자와 공백을 모두 제거하여 순수 글자만 비교
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


def compare_with_content_matching(pdf1_path, pdf2_path):
  print("=" * 65)
  print(" ✈️ 공항 NOTAM 분석기 (섹션 정확도 극대화 버전)")
  print("=" * 65)

  print(
      "\n[안내] 본인의 운항(비행) 시간을 입력해 주세요."
      " (예: YYMMDDHHMM 형식, 예시: 2603150800)"
  )
  f_start_str = input(" ▶ 비행 시작 시간 (출발 등): ")
  f_end_str = input(" ▶ 비행 종료 시간 (도착 등): ")

  flight_start = parse_datetime_input(f_start_str)
  flight_end = parse_datetime_input(f_end_str)

  text1 = extract_text_from_pdf(pdf1_path)
  text2 = extract_text_from_pdf(pdf2_path)

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
    print("\n새로 추가된 NOTAM이 없습니다.")
    return

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

  print("\n" + "=" * 65)
  print(" [완벽 분류 및 PDF 순서 기준 리포트]")
  print("=" * 65)

  for airport in sorted(structured_output.keys()):
    print(f"\n✈️ 공항: {airport}")
    for section in SECTIONS + ["OTHER"]:
      if section in structured_output[airport]:
        items = structured_output[airport][section]
        print(f"    📂 [{section}]")
        for notam_num, matched_old, affecting, body in items:
          if matched_old:
            old_str = ", ".join(matched_old)
            status_tag = f"🔄 [내용 동일 / 번호 변경] (구 번호: {old_str})"
          else:
            if affecting and flight_start:
              status_tag = f"🚨 [완전 신규 / 영향 있음]"
            else:
              status_tag = f"➕ [완전 신규 (참고)]"

          print(f"\n      {status_tag} {notam_num}")
          for body_line in body.splitlines():
            print(f"          {body_line}")


# --- 실행 부분 ---
compare_with_content_matching("old.pdf", "new.pdf")
