import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import csv
import time
import urllib3

# 1. 基础配置
# -----------------------------------------------------------
BASE_URL = "https://jwc.njupt.edu.cn/1594/"
START_PAGE = 1
# 根据网页显示总共3802条记录，每页14条，大约有272页
# 建议先设置成 5 页测试，测试没问题后改为 272 跑全量
END_PAGE = 5  
OUTPUT_FILE = "njupt_jwc_final.csv"

# 伪装成浏览器
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://jwc.njupt.edu.cn/1594/list.htm"
}

# 忽略学校网站常见的 SSL 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# 2. 辅助函数
# -----------------------------------------------------------
def get_page_url(page_num):
    """根据页码生成对应的 URL"""
    if page_num == 1:
        return f"{BASE_URL}list.htm"
    else:
        return f"{BASE_URL}list{page_num}.htm"

def parse_page(html_content, base_url):
    """解析 HTML 提取数据，使用截图确认的精确选择器"""
    soup = BeautifulSoup(html_content, 'html.parser')
    data_list = []

    # [截图确认] 1. 定位新闻列表的大容器: div.col_news_con
    container = soup.select_one('div.col_news_con')
    if not container:
        print("  [!] 警告：未找到新闻列表容器 (div.col_news_con)")
        return []

    # [截图确认] 2. 获取所有新闻行: li.news
    # 虽然截图显示是 li.news.n1.clearfix，但 .news 是核心类名，选中它就能选中所有行
    news_items = container.select('li.news')

    for item in news_items:
        try:
            # [截图确认] 3. 提取标题和链接: span.news_title 下的 a 标签
            title_span = item.select_one('span.news_title')
            a_tag = title_span.find('a') if title_span else item.find('a')

            if not a_tag:
                continue

            title = a_tag.get('title') or a_tag.get_text(strip=True)
            link = urljoin(base_url, a_tag.get('href'))

            # [截图确认] 4. 提取时间: span.news_meta
            # 这是你最后一张图补充的关键信息
            date_span = item.select_one('span.news_meta')
            date = date_span.get_text(strip=True) if date_span else ""

            data_list.append({
                'title': title,
                'date': date,
                'link': link
            })

        except Exception as e:
            print(f"  [!] 解析单行出错: {e}")
            continue

    return data_list


# 3. 主程序
# -----------------------------------------------------------
def main():
    print(f"=== 开始爬取南京邮电大学教务处通知 ===")
    print(f"目标范围: 第 {START_PAGE} 页 到 第 {END_PAGE} 页")
    print(f"结果文件: {OUTPUT_FILE}\n")

    # 初始化 CSV 文件，写入表头
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['title', 'date', 'link'])
        writer.writeheader()

    total_count = 0
    start_time = time.time()

    for page in range(START_PAGE, END_PAGE + 1):
        url = get_page_url(page)
        print(f"正在处理第 {page} 页: {url} ...", end="", flush=True)

        try:
            # 发送请求
            response = requests.get(url, headers=HEADERS, verify=False, timeout=10)
            response.encoding = 'utf-8' # 显式指定编码

            if response.status_code == 200:
                # 解析数据
                rows = parse_page(response.text, url)
                count = len(rows)
                
                if count > 0:
                    # 写入文件
                    with open(OUTPUT_FILE, 'a', newline='', encoding='utf-8-sig') as f:
                        writer = csv.DictWriter(f, fieldnames=['title', 'date', 'link'])
                        writer.writerows(rows)
                    total_count += count
                    print(f" 成功获取 {count} 条")
                else:
                    print(" 无数据 (请检查选择器或网络)")
            else:
                print(f" 请求失败 (状态码: {response.status_code})")

        except Exception as e:
            print(f" 发生异常: {e}")

        # 礼貌性延时，防止对学校服务器造成压力
        time.sleep(1)

    duration = time.time() - start_time
    print(f"\n=== 爬取结束 ===")
    print(f"共耗时: {duration:.2f} 秒")
    print(f"共获取: {total_count} 条数据")
    print(f"数据已保存至当前目录下的: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()