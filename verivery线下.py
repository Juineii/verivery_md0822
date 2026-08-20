import requests
import time
import csv
import os
import subprocess
import threading
from datetime import datetime

# ================== 配置 ==================
PRODUCTS = {
    "VERIVERY线下团签": 13429,
    "DONGHEON_DIY":13430,
    "GYEHYEON_DIY":13431,
    "YEONHO_DIY":13432,
    "YONGSEUNG_DIY":13433,
    "KANGMIN_DIY": 13434
}

GITHUB_REPO = "Juineii/verivery_md0822"    # 请替换为您的仓库名
GITHUB_BRANCH = "main"                    # 分支名（main 或 master）
PUSH_INTERVAL = 60                        # 推送检查间隔（秒）

# 基础URL（不含prod_idx）
BASE_URL = "https://www.cn.musicndrama.com/ajax/oms/OMS_get_product.cm?prod_idx="
REFERER_BASE = "https://www.cn.musicndrama.com/shop_view/?idx="
HEADERS_TEMPLATE = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0',
    'Cookie': 'al=KR'
}

# 初始化每个商品的上一库存（字典）
prev_stocks = {name: None for name in PRODUCTS}

# 全局锁和计数器
lines_since_last_push = 0   # 自上次推送后写入的行数（所有商品合计）
lines_lock = threading.Lock()
file_lock = threading.Lock()


# ================== Git 推送函数（支持多个文件） ==================
def git_push_update(file_paths):
    """
    将指定的多个 CSV 文件提交并推送到 GitHub
    返回: True 表示推送成功, False 表示失败
    """
    try:
        token = os.environ.get('GITHUB_TOKEN')
        if not token:
            print("⚠️ 环境变量 GITHUB_TOKEN 未设置，跳过 Git 推送")
            return False

        remote_url = f"https://{token}@github.com/{GITHUB_REPO}.git"

        # 依次添加所有 CSV 文件到暂存区（只添加存在的）
        for fpath in file_paths:
            if os.path.exists(fpath):
                subprocess.run(['git', 'add', fpath], check=True, capture_output=True, timeout=30)

        # 检查是否有文件变化（避免空提交）
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True, timeout=30)
        if result.returncode != 0:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_msg = f"自动更新数据 {timestamp}"
            subprocess.run(['git', 'commit', '-m', commit_msg], check=True, capture_output=True, timeout=30)
            subprocess.run(
                ['git', 'push', remote_url, f'HEAD:{GITHUB_BRANCH}'],
                check=True, capture_output=True, text=True, timeout=30
            )
            print(f"✅ 已推送到 GitHub: {commit_msg}")
            return True
        else:
            print("⏭️ CSV 文件无变化，跳过推送")
            return True  # 无变化但逻辑上算成功，避免重复尝试

    except subprocess.TimeoutExpired:
        print("❌ Git 操作超时 (30秒)，推送失败")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ Git 操作失败: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        print(f"❌ 推送过程中发生错误: {e}")
        return False


def save_to_csv(product_name, data_row):
    """
    将单条库存变化追加写入对应商品的 CSV 文件，并累加计数器（不触发推送）
    data_row: list, 格式 [时间, 商品名称, 库存变化, 单笔销量]
    """
    global lines_since_last_push

    csv_file = f"{product_name}.csv"          # 每个商品独立 CSV 文件名
    fieldnames = ["时间", "商品名称", "库存变化", "单笔销量"]

    try:
        file_exists = os.path.exists(csv_file)

        # 追加写入（utf-8-sig 保证 Excel 兼容）
        with file_lock:  # 与推送线程互斥
            with open(csv_file, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                row_dict = {
                    "时间": data_row[0],
                    "商品名称": data_row[1],
                    "库存变化": data_row[2],
                    "单笔销量": data_row[3]
                }
                writer.writerow(row_dict)

        # 打印本次记录（与原风格一致）
        print(f"{data_row[0]} - 商品名称: {data_row[1]}, 库存变化: {data_row[2]}, 单笔销量: {data_row[3]}")

        # 更新计数器（线程安全）
        with lines_lock:
            lines_since_last_push += 1
        return True

    except Exception as e:
        print(f"写入CSV文件失败 ({product_name}): {e}")
        return False


# ================== 推送线程 ==================
def push_worker():
    global lines_since_last_push
    while True:
        time.sleep(PUSH_INTERVAL)
        with lines_lock:
            pending = lines_since_last_push
        if pending > 0:
            print(f"⏰ 定时推送：有 {pending} 条新数据待推送")
            # 收集所有商品的 CSV 文件路径
            all_csv_files = [f"{name}.csv" for name in PRODUCTS]
            with file_lock:          # 推送期间禁止写入，保证文件完整
                success = git_push_update(all_csv_files)
            if success:
                with lines_lock:
                    lines_since_last_push = 0
                print("✅ 推送成功，计数器已归零")
            else:
                print("⚠️ 推送失败，下次再试")


# ================== 主监控循环 ==================
if __name__ == "__main__":
    # 启动推送守护线程
    push_thread = threading.Thread(target=push_worker, daemon=True)
    push_thread.start()

    try:
        while True:
            # 遍历所有商品
            for product_name, prod_idx in PRODUCTS.items():
                try:
                    # 构造该商品的 URL 和 Referer
                    url = f"{BASE_URL}{prod_idx}"
                    headers = {
                        **HEADERS_TEMPLATE,
                        "Referer": f"{REFERER_BASE}{prod_idx}"
                    }

                    response = requests.get(url, headers=headers)
                    response.raise_for_status()

                    data = response.json()
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if 'data' in data and 'options_detail' in data['data'] and len(data['data']['options_detail']) > 0:
                        # 仅取第一个选项
                        current_stock = data['data']['options_detail'][0]['stock']
                        prev_stock = prev_stocks[product_name]

                        if prev_stock is None:
                            # 记录初始库存
                            data_row = [
                                current_time,
                                product_name,
                                f"初始库存: {current_stock}",
                                0
                            ]
                            save_to_csv(product_name, data_row)
                            prev_stocks[product_name] = current_stock
                        elif current_stock != prev_stock:
                            diff = prev_stock - current_stock
                            data_row = [
                                current_time,
                                product_name,
                                f"{prev_stock} -> {current_stock}",
                                diff
                            ]
                            save_to_csv(product_name, data_row)
                            prev_stocks[product_name] = current_stock
                        # 库存未变化则无操作
                    else:
                        print(f"意外的JSON结构（{product_name}）：options_detail 未找到或为空")

                except requests.exceptions.RequestException as e:
                    print(f"请求失败 ({product_name}): {e}")
                except ValueError as e:
                    print(f"JSON解析失败 ({product_name}): {e}")
                except KeyError as e:
                    print(f"键错误 ({product_name}): {e}")

            time.sleep(10)   # 所有商品检查完后等待 10 秒

    except KeyboardInterrupt:
        print("\n监控程序被用户终止")
        # 退出前推送剩余未推送的数据
        with lines_lock:
            pending = lines_since_last_push
        if pending > 0:
            print(f"正在推送剩余的 {pending} 条数据...")
            all_csv_files = [f"{name}.csv" for name in PRODUCTS]
            with file_lock:
                success = git_push_update(all_csv_files)
            if success:
                print("✅ 剩余数据已推送")
            else:
                print("⚠️ 剩余数据推送失败，请手动检查")
        else:
            print("无待推送数据")