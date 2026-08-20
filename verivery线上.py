import requests
import time
import os
import subprocess
import csv
import threading
from datetime import datetime

# ================== Git 推送配置 ==================
GITHUB_REPO = "Juineii/pow_md0719"   # 请替换为您的仓库名
GITHUB_BRANCH = "main"                  # 分支名（main 或 master）
PUSH_INTERVAL = 60                      # 推送检查间隔（秒）

# ================== 产品配置 ==================
PRODUCTS = {
    "POW线上团签": 13303,
    "YORCH影通": 13304,
    "HYUNBIN影通": 13305,
    "JUNGBIN影通": 13306,
    "DONGYEON影通": 13307,
    "HONG影通": 13308
}

BASE_URL = "https://en.musicndrama.com/ajax/oms/OMS_get_product.cm?prod_idx="
REFERER_BASE = "https://en.musicndrama.com/shop_view/?idx="
CHECK_INTERVAL = 10

HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}

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

        # 依次添加所有 CSV 文件到暂存区
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
            return True   # 无变化也视为成功，避免重复尝试

    except subprocess.TimeoutExpired:
        print("❌ Git 操作超时 (30秒)，推送失败")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ Git 操作失败: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        print(f"❌ 推送过程中发生错误: {e}")
        return False


class StockMonitor:
    def __init__(self):
        if not PRODUCTS:
            raise ValueError("PRODUCTS 不能为空")

        # 每个产品独立 CSV 文件名（直接使用产品名，不含路径）
        self.csv_files = {name: f"{name}.csv" for name in PRODUCTS}

        # 存储每个产品每个 idx 的上次库存
        self.previous_stocks = {name: {} for name in PRODUCTS}
        # 存储每个产品每个 idx 的累计销量（仅内部使用）
        self.sales_by_idx = {name: {} for name in PRODUCTS}

        # 线程安全锁（多个文件共用一把锁，保证写入和推送互斥）
        self.file_lock = threading.Lock()
        self.lines_lock = threading.Lock()

        # 批量推送相关变量（全局累计，所有产品共用）
        self.lines_since_last_push = 0   # 自上次推送后写入的行数

        self._setup_csv_files()

        # 启动推送守护线程
        self._start_push_worker()

    def _csv_path(self, product_name):
        """返回指定产品 CSV 文件的完整路径（与脚本同一目录）"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, self.csv_files[product_name])

    def _all_csv_paths(self):
        """返回所有产品 CSV 文件的完整路径列表"""
        return [self._csv_path(name) for name in PRODUCTS]

    def _setup_csv_files(self):
        """为每个产品创建 CSV 文件（如果不存在），并写入表头"""
        for product_name in PRODUCTS:
            csv_file = self._csv_path(product_name)
            if not os.path.exists(csv_file):
                try:
                    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                        writer = csv.writer(f)
                        writer.writerow(["时间", "商品名称", "库存变化", "单笔销量"])
                except Exception as e:
                    print(f"❌ 创建 CSV 文件 {csv_file} 失败: {e}")

    def _get_display_name(self, idx, order_index):
        """根据选项顺序返回显示名称：第1个 -> 'kkt', 第2个 -> 'line', 其余 -> 原始idx"""
        if order_index == 0:
            return "kkt"
        elif order_index == 1:
            return "line"
        else:
            return str(idx)

    def _write_csv_row(self, product_name, timestamp, display_name, stock_change, sales):
        """
        将一条记录追加写入对应产品的 CSV 文件。
        CSV 列：时间, 商品名称, 库存变化, 单笔销量
        """
        csv_file = self._csv_path(product_name)
        fieldnames = ["时间", "商品名称", "库存变化", "单笔销量"]

        try:
            # 追加写入（文件已存在且含表头）
            with self.file_lock:  # 与推送线程互斥
                with open(csv_file, 'a', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    row_dict = {
                        "时间": timestamp,
                        "商品名称": display_name,
                        "库存变化": stock_change,
                        "单笔销量": sales
                    }
                    writer.writerow(row_dict)

            # 控制台打印（保留产品名标识）
            print(f"已记录: [{product_name}] {timestamp}, {display_name}, {stock_change}, {sales}")

            # 更新计数器（线程安全）
            with self.lines_lock:
                self.lines_since_last_push += 1

        except Exception as e:
            print(f"❌ 写入 CSV 错误 ({product_name}): {e}")

    def _push_worker(self):
        """推送守护线程函数"""
        while True:
            time.sleep(PUSH_INTERVAL)
            with self.lines_lock:
                pending = self.lines_since_last_push
            if pending > 0:
                print(f"⏰ 定时推送：有 {pending} 条新数据待推送")
                # 推送期间禁止写入，保证所有文件完整
                with self.file_lock:
                    # 获取所有 CSV 路径
                    all_csv = self._all_csv_paths()
                    success = git_push_update(all_csv)
                if success:
                    with self.lines_lock:
                        self.lines_since_last_push = 0
                    print("✅ 推送成功，计数器已归零")
                else:
                    print("⚠️ 推送失败，下次再试")

    def _start_push_worker(self):
        """启动推送守护线程（daemon 线程）"""
        thread = threading.Thread(target=self._push_worker, daemon=True)
        thread.start()

    def fetch_stocks(self):
        for product_name, product_id in PRODUCTS.items():
            url = f"{BASE_URL}{product_id}"
            headers = {
                **HEADERS,
                "Referer": f"{REFERER_BASE}{product_id}",
            }

            try:
                response = requests.get(url, headers=headers, timeout=10)
                data = response.json()

                if "data" not in data or "options_detail" not in data["data"]:
                    print(f"❌ [{product_name}] Stock data not found")
                    continue

                options = data["data"]["options_detail"]
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 构建 idx -> 顺序索引 的映射（0-based）
                idx_to_order = {opt["idx"]: idx for idx, opt in enumerate(options)}

                # 情况1：尚未初始化该产品的任何 idx（第一次抓取）
                if not self.previous_stocks[product_name]:
                    for opt in options:
                        idx = opt["idx"]
                        stock = opt["stock"]
                        order = idx_to_order[idx]
                        display = self._get_display_name(idx, order)

                        self.previous_stocks[product_name][idx] = stock
                        self.sales_by_idx[product_name][idx] = 0

                        self._write_csv_row(
                            product_name, current_time, display,
                            f"初始销量：{stock}", 0
                        )
                    continue

                # 情况2：已初始化，比较每个 idx 的变化
                for opt in options:
                    idx = opt["idx"]
                    current_stock = opt["stock"]
                    previous_stock = self.previous_stocks[product_name].get(idx)
                    order = idx_to_order[idx]
                    display = self._get_display_name(idx, order)

                    # 新出现的 idx（理论上很少见）
                    if previous_stock is None:
                        self.previous_stocks[product_name][idx] = current_stock
                        self.sales_by_idx[product_name][idx] = 0
                        self._write_csv_row(
                            product_name, current_time, display,
                            f"初始销量：{current_stock}", 0
                        )
                        continue

                    # 库存发生变化
                    if current_stock != previous_stock:
                        diff = previous_stock - current_stock
                        if diff > 0:
                            self.sales_by_idx[product_name][idx] += diff
                        change_desc = f"{previous_stock}->{current_stock}"
                        self._write_csv_row(
                            product_name, current_time, display,
                            change_desc, diff
                        )
                        # 更新上次库存
                        self.previous_stocks[product_name][idx] = current_stock
                    # 无变化时不写入

            except Exception as e:
                print(f"❌ [{product_name}] Error: {e}")


if __name__ == "__main__":
    monitor = StockMonitor()

    try:
        while True:
            monitor.fetch_stocks()
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        print("\n监控程序被用户终止")
        # 退出前推送剩余未推送的数据
        with monitor.lines_lock:
            pending = monitor.lines_since_last_push
        if pending > 0:
            print(f"正在推送剩余的 {pending} 条数据...")
            with monitor.file_lock:
                all_csv = monitor._all_csv_paths()
                success = git_push_update(all_csv)
            if success:
                print("✅ 剩余数据已推送")
            else:
                print("⚠️ 剩余数据推送失败，请手动检查")
        else:
            print("无待推送数据")