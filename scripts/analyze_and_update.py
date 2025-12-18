import os
import json
import glob
import re
import logging
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

try:
    import pandas as pd
    import openpyxl
except ImportError:
    logger.error("Missing required libraries. Please run: pip install pandas openpyxl")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')
DATA_DIR = os.path.join(PUBLIC_DIR, 'data')
MANIFEST_PATH = os.path.join(PUBLIC_DIR, 'manifest.json')
OUTPUT_DOC_PATH = os.path.join(DATA_DIR, 'DATA_INVENTORY.md')
MERGED_JSON_PATH = os.path.join(DATA_DIR, 'all_exams.json')

os.makedirs(DATA_DIR, exist_ok=True)

FIELD_MAPPING = {
    "campus": ["校区", "校区名称"],
    "course": ["课程名称", "课程", "考试课程"],
    "course_code": ["课程代码", "选课课号"],
    "class_name": ["班级名称", "班级", "班级代码", "行政班级"],
    "teacher": ["任课教师", "教师", "监考教师"],
    "location": ["考试教室", "教室名称", "地点", "考试地点"],
    "raw_time": ["考试时间", "时间"],
    "count": ["人数", "学生人数", "考试人数"],
    "school": ["开课学院", "学院"],
    "student_school": ["学生所在学院", "所在学院"],
    "major": ["专业名称", "专业"],
    "grade": ["年级"],
    "notes": ["备注"]
}

REGEX_CHINESE = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?(\d{1,2}:\d{2})\s*[-~至]\s*(\d{1,2}:\d{2})')
REGEX_ISO = re.compile(r'\(?(\d{4}-\d{1,2}-\d{1,2})\)?.*?(\d{1,2}:\d{2})\s*[-~至]\s*(\d{1,2}:\d{2})')


def get_xlsx_files() -> List[str]:
    return glob.glob(os.path.join(DATA_DIR, '*.xlsx'))


def clean_text(text: Any) -> str:
    if pd.isna(text) or text == "" or text is None:
        return ""
    return str(text).replace('\xa0', ' ').strip()


def parse_exam_time(time_val: Any) -> Dict[str, Any]:
    if pd.isna(time_val) or time_val == "":
        return {"error": "Time field is empty"}

    if isinstance(time_val, (datetime, pd.Timestamp)):
        time_str = str(time_val)
    else:
        time_str = clean_text(time_val)

    start_dt = None
    end_dt = None
    date_str = ""

    try:
        match_cn = REGEX_CHINESE.search(time_str)
        match_iso = REGEX_ISO.search(time_str)

        if match_cn:
            year, month, day, start_hm, end_hm = match_cn.groups()
            date_str = f"{year}-{int(month):02d}-{int(day):02d}"
        elif match_iso:
            d_str, start_hm, end_hm = match_iso.groups()
            try:
                date_str = datetime.strptime(d_str, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                date_str = d_str
        else:
            return {"error": "Unrecognized date format"}

        start_str = f"{date_str} {start_hm}:00"
        end_str = f"{date_str} {end_hm}:00"

        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")

        duration = int((end_dt - start_dt).total_seconds() / 60)

        return {
            "start_timestamp": start_dt.isoformat(),
            "end_timestamp": end_dt.isoformat(),
            "duration_minutes": duration,
            "date": date_str,
            "error": None
        }
    except Exception as e:
        return {"error": f"Parsing exception: {str(e)}"}


def process_single_file(file_path: str) -> Optional[Dict[str, Any]]:
    filename = os.path.basename(file_path)
    logger.info(f"Processing file: {filename}")
    
    try:
        df = pd.read_excel(file_path, engine='openpyxl')
        
        current_file_mapping = {}
        for std_key, possible_cols in FIELD_MAPPING.items():
            found_col = None
            for col in possible_cols:
                if col in df.columns:
                    found_col = col
                    break
            current_file_mapping[std_key] = found_col
        
        clean_data = []
        validation_errors = []
        records = df.to_dict(orient='records')
        
        for idx, row in enumerate(records, start=2):
            processed_row = {
                '_source_file': filename,
                '_row_index': idx,
                'id': f"{filename}-{idx}"
            }
            
            for std_key, original_col in current_file_mapping.items():
                if original_col:
                    val = row.get(original_col)
                    if std_key == 'count':
                        try:
                            processed_row[std_key] = int(val) if pd.notnull(val) else 0
                        except (ValueError, TypeError):
                            processed_row[std_key] = 0
                    else:
                        processed_row[std_key] = clean_text(val)
                else:
                    processed_row[std_key] = "" if std_key != 'count' else 0

            raw_time_val = row.get(current_file_mapping.get('raw_time'))
            processed_row['raw_time'] = clean_text(raw_time_val)

            if raw_time_val:
                time_result = parse_exam_time(raw_time_val)
                if time_result.get('error'):
                    validation_errors.append(f"Row {idx}: {time_result['error']} (Raw: '{processed_row['raw_time']}')")
                    processed_row['parse_error'] = time_result['error']
                else:
                    processed_row.update(time_result)
            else:
                processed_row['parse_error'] = "Missing time data"

            clean_data.append(processed_row)

        return {
            "filename": filename,
            "row_count": len(df),
            "validation_errors": validation_errors,
            "total_errors": len(validation_errors),
            "column_details": {col: str(df[col].dtype) for col in df.columns},
            "raw_data": clean_data,
            "samples": clean_data[:3] if clean_data else []
        }

    except Exception as e:
        logger.error(f"Failed to process {file_path}: {e}", exc_info=True)
        return None


def generate_markdown_report(analyses: List[Dict], total_records: int) -> str:
    lines = ["# Data Inventory & Quality Report", ""]
    lines.append(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total Files Processed:** {len(analyses)}")
    lines.append(f"**Total Records Extracted:** {total_records}")
    lines.append("")

    for analysis in analyses:
        status_icon = "✅" if analysis['total_errors'] == 0 else "⚠️"
        lines.append(f"## {status_icon} File: `{analysis['filename']}`")
        lines.append(f"- **Row Count:** {analysis['row_count']}")
        
        if analysis['total_errors'] > 0:
            lines.append(f"- **Validation Warnings:** {analysis['total_errors']}")
            lines.append("  > **Error Samples:**")
            for err in analysis['validation_errors'][:5]:
                lines.append(f"  - {err}")
        else:
            lines.append("- **Validation:** Passed")

        lines.append("")
        lines.append("### Data Preview (Top 3 Rows)")
        
        if analysis['samples']:
            # Create a Markdown table for samples
            keys = [k for k in analysis['samples'][0].keys() if k not in ['id', '_source_file', '_row_index']]
            
            # Header
            lines.append("| " + " | ".join(keys) + " |")
            # Separator
            lines.append("| " + " | ".join(["---"] * len(keys)) + " |")
            # Rows
            for sample in analysis['samples']:
                row_vals = [str(sample.get(k, '')) for k in keys]
                lines.append("| " + " | ".join(row_vals) + " |")
        else:
            lines.append("_No data extracted_")

        lines.append("")
        lines.append("---")
        lines.append("")
        
    return "\n".join(lines)


def main():
    logger.info("Starting data extraction process...")
    files = get_xlsx_files()
    
    if not files:
        logger.warning("No .xlsx files found in 'data/' directory.")
        return

    analyses = []
    all_rows = []

    for f in files:
        result = process_single_file(f)
        if result:
            analyses.append(result)
            all_rows.extend(result['raw_data'])

    logger.info(f"Saving {len(all_rows)} records to {MERGED_JSON_PATH}...")
    with open(MERGED_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_rows, f, ensure_ascii=False, separators=(',', ':'))

    report_content = generate_markdown_report(analyses, len(all_rows))
    with open(OUTPUT_DOC_PATH, 'w', encoding='utf-8') as f:
        f.write(report_content)

    manifest = {
        "generated_at": datetime.now().isoformat(),
        "files_processed": [a['filename'] for a in analyses],
        "total_records": len(all_rows)
    }
    with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    logger.info("Data processing complete.")


if __name__ == "__main__":
    main()