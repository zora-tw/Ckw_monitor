# check_stock_api.py
import requests
import json
import datetime
import time # 引入 time 模組用於延遲
from bs4 import BeautifulSoup # 引入 BeautifulSoup 用於解析 HTML

# --- 請在此處替換為您的實際資訊 ---
BASE_URL = 'https://chiikawamarket.jp'

# 您要監控的商品網址清單
# 程式將會自動從這些網址中解析出 Variant ID 和 Product ID
PRODUCTS_URLS_TO_MONITOR = [
    'https://chiikawamarket.jp/products/4582662964709', # 範例商品
    # 'https://chiikawamarket.jp/products/YOUR_OTHER_PRODUCT_URL_HERE', # 加入其他要監控的商品網址
    # 'https://nagano-market.jp/products/YOUR_NAGANO_MARKET_URL_HERE', # 也支援 nagano-market.jp
]
# --- 替換結束 ---

# 線性搜尋的最大上限值。程式將從 1 開始，一個一個嘗試直到此上限或遇到庫存極限。
# 此值應足夠大，以涵蓋商品的任何可能庫存量，同時避免過多不必要的請求。
LINEAR_SEARCH_UPPER_BOUND = 2000 # 將上限設定為一個較為合理的數字，例如 2000

class CartAPI:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session()

    def _send_request_with_retry(self, method, url_path, retries=3, backoff_factor=0.5, **kwargs):
        """
        發送 HTTP 請求的輔助函數，帶有重試機制。
        處理連線錯誤和可重試的 HTTP 狀態碼 (例如 5xx)。
        會返回 Response 物件，由呼叫者處理其狀態碼。
        """
        url = f"{self.base_url}{url_path}"
        for i in range(retries):
            try:
                response = self.session.request(method, url, **kwargs)
                return response # 返回 Response 物件，呼叫者會檢查其狀態碼
            except requests.exceptions.ConnectionError as e:
                wait_time = backoff_factor * (2 ** i)
                print(f"  連線失敗，第 {i+1}/{retries} 次重試，等待 {wait_time:.1f} 秒...")
                time.sleep(wait_time)
            except Exception as e: # 捕獲其他所有未知錯誤
                print(f"  請求發生未知錯誤: {e}")
                raise e # 重新拋出錯誤
        raise requests.exceptions.RequestException(f"請求在 {retries} 次重試後仍然失敗: {url}")

    def get_cart(self):
        # 獲取購物車內容，使用重試機制，並期望成功狀態碼
        response = self._send_request_with_retry("GET", "/cart.js", headers={"accept": "*/*"})
        response.raise_for_status() # 如果是 4xx 或 5xx 錯誤，將拋出異常 (除了 add_item)
        return response.json().get('items')

    def add_item(self, variant_id, product_id, quantity):
        """
        將商品加入購物車。此方法會返回 Response 物件，
        呼叫者 (check_product_stock) 需要自行檢查其狀態碼，尤其是 422。
        """
        data = {
            "form_type": "product",
            "utf8": "✓",
            "id": variant_id,
            "quantity": quantity,
            "product-id": product_id,
            "section-id": "template--18391309091057__main", # 此值可能需要根據網站實際情況調整
        }
        # requests 會自動處理 form-data 的 Content-Type
        return self._send_request_with_retry("POST", "/cart/add.js", data=data, headers={"X-Requested-With": "XMLHttpRequest"})

    def get_item_quantity_in_cart(self, variant_id):
        items = self.get_cart() # get_cart 已經包含重試和錯誤檢查
        if items:
            for item in items:
                if str(item.get('id')) == str(variant_id):
                    return item.get('quantity', -1)
        return -1

    def remove_item(self, variant_id):
        items = self.get_cart() # get_cart 已經包含重試和錯誤檢查
        if not items:
            return 0

        line_index = -1
        current_quantity = 0
        for i, item in enumerate(items):
            if str(item.get('id')) == str(variant_id):
                line_index = i + 1
                current_quantity = item.get('quantity', 0)
                break

        if line_index != -1:
            payload = {"line": line_index, "quantity": 0}
            response = self._send_request_with_retry("POST", "/cart/change.js", json=payload, headers={"content-type": "application/json"})
            response.raise_for_status() # 對於移除操作，期望成功狀態碼
            return current_quantity
        return 0

# 新增函數：從商品網址中提取 Variant ID 和 Product ID
def get_ids_from_product_url(product_url):
    """
    從商品頁面 HTML 中解析出 Variant ID 和 Product ID。
    參考了原始 UserScript 中獲取 ID 的邏輯。
    """
    print(f"解析網址: {product_url} 以獲取商品 ID...")
    try:
        # 使用 requests 獲取網頁內容
        response = requests.get(product_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        response.raise_for_status() # 檢查請求是否成功

        # 使用 BeautifulSoup 解析 HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # 嘗試從 input[name="product-id"] 獲取 productId
        product_id_input = soup.find('input', {'name': 'product-id'})
        product_id = product_id_input.get('value') if product_id_input else None

        variant_id = None
        # 嘗試從 .product-form--variant-select 獲取 variant ID
        # 原始 UserScript 是 document.getElementsByClassName("product-form--variant-select")?.[0]?.children?.[0]?.getAttribute("value");
        # 對應 BeautifulSoup 查找方式
        variant_select_element = soup.select_one('.product-form--variant-select select') # 尋找 select 標籤
        if variant_select_element:
            selected_option = variant_select_element.find('option', selected=True) # 查找被選中的選項
            if not selected_option: # 如果沒有選中項，取第一個選項
                selected_option = variant_select_element.find('option')
            if selected_option:
                variant_id = selected_option.get('value')

        # 如果上面沒找到 variant ID，嘗試從 .product__pickup-availabilities 獲取
        # 原始 UserScript 是 document.getElementsByClassName("product__pickup-availabilities")?.[0]?.getAttribute("data-variant-id");
        if not variant_id:
            pickup_availabilities = soup.select_one('.product__pickup-availabilities')
            if pickup_availabilities:
                variant_id = pickup_availabilities.get('data-variant-id')
        
        # 額外策略: 從 URL 路徑中提取 variant ID (通常適用於單一商品)
        if not variant_id:
            path_segments = product_url.split('/')
            if path_segments and path_segments[-1].isdigit(): # 檢查最後一段是否是數字
                variant_id = path_segments[-1]
            elif path_segments and path_segments[-2].isdigit() and 'products' in path_segments[-3]: # 處理 /collections/xxx/products/ID 形式
                variant_id = path_segments[-2]


        if not product_id:
             # 如果 product_id 還沒找到，嘗試在頁面 script 標籤中找 Shopify product json
            for script in soup.find_all('script'):
                if 'window.Shopify.Product' in script.text:
                    try:
                        # 找到包含 product JSON 的行
                        start_index = script.text.find('window.Shopify.Product = ') + len('window.Shopify.Product = ')
                        end_index = script.text.find('};', start_index) + 1
                        if start_index != -1 and end_index != -1:
                            product_json_str = script.text[start_index:end_index]
                            product_data = json.loads(product_json_str)
                            product_id = str(product_data.get('id'))
                            # 同時也可以從這裡獲取 variant_id，如果有多個 variants
                            if not variant_id and product_data.get('selected_or_first_available_variant'):
                                variant_id = str(product_data['selected_or_first_available_variant'].get('id'))
                            break
                    except json.JSONDecodeError:
                        continue # 不是有效的 JSON
                    except Exception as e:
                        print(f"解析 Shopify Product JSON 失敗: {e}")
                        continue
        
        print(f"從 {product_url} 提取結果: Variant ID = {variant_id}, Product ID = {product_id}")
        return variant_id, product_id

    except requests.exceptions.RequestException as e:
        print(f"錯誤: 無法訪問網址 {product_url} - {e}")
        return None, None
    except Exception as e:
        print(f"錯誤: 解析網址 {product_url} 失敗 - {e}")
        return None, None


def check_product_stock(product_info):
    variant_id = product_info['variant_id']
    product_id = product_info['product_id']
    product_name = product_info.get('name', f'商品 ID: {variant_id}') # 友善的名稱

    if not variant_id or not product_id:
        print(f"跳過商品 '{product_name}'，因為無法獲取完整的 Variant ID 或 Product ID。")
        return

    cart_api = CartAPI(BASE_URL)
    actual_stock = 0 # 初始化實際庫存為 0

    print(f"\n--- [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 檢查商品: {product_name} ---")

    try:
        # 步驟 1: 嘗試移除現有商品以確保購物車是乾淨的
        try:
            initial_quantity_in_cart = cart_api.remove_item(variant_id)
            if initial_quantity_in_cart > 0:
                print(f"已從購物車中移除了 {initial_quantity_in_cart} 個商品 ID: {variant_id} (檢查前清理)。")
        except requests.exceptions.RequestException as e:
            print(f"警告: 嘗試移除商品時發生錯誤 (可能購物車為空或網路問題): {e}")

        # 步驟 2: 使用線性搜尋法找出可加入購物車的最大數量 (即實際庫存)
        print(f"開始線性搜尋，尋找 '{product_name}' 的實際庫存...")
        max_addable_quantity_found = 0
        
        # 從 1 開始，一個一個嘗試加入購物車
        for q_test in range(1, LINEAR_SEARCH_UPPER_BOUND + 1):
            print(f"  嘗試加入數量: {q_test}")
            add_response = cart_api.add_item(variant_id, product_id, q_test)
            
            if 200 <= add_response.status_code < 300: # 請求成功 (2xx 狀態碼)
                # 如果成功加入 q_test 數量，表示庫存至少有這麼多
                max_addable_quantity_found = q_test
                # 立即清理購物車，為下次迭代準備
                cart_api.remove_item(variant_id)
                
                # 為了避免不必要的 API 呼叫，只有當實際加入數量與嘗試數量一致時，才繼續嘗試更高的數量
                # 否則，如果 API 在 2xx 狀態下也限制了數量，那麼 quantity_in_cart 就是最終庫存
                quantity_in_cart_after_add = cart_api.get_item_quantity_in_cart(variant_id)
                if quantity_in_cart_after_add < q_test and quantity_in_cart_after_add >= 0:
                     max_addable_quantity_found = quantity_in_cart_after_add
                     print(f"  實際加入數量為 {quantity_in_cart_after_add}，已達上限。")
                     break # 找到上限，跳出迴圈
                elif quantity_in_cart_after_add == -1: # 獲取購物車數量異常
                    print(f"  警告: 獲取購物車數量異常: {quantity_in_cart_after_add} for quantity {q_test}")
                    # 此時 max_addable_quantity_found 保持為上次成功的值
                    break # 跳出迴圈

            elif add_response.status_code == 422: # 請求失敗，通常是因為數量超過庫存
                # 這表示 q_test 數量太高了，因此實際最大可加入數量是 q_test - 1
                max_addable_quantity_found = q_test - 1
                print(f"  數量 {q_test} 過高，API 返回 422。最大可加入數量為 {max_addable_quantity_found}。")
                break # 找到實際庫存，跳出迴圈
            else:
                # 其他非 2xx/非 422 的錯誤狀態碼 (例如 404, 500 等)
                print(f"  錯誤: 加入購物車請求失敗 (狀態碼: {add_response.status_code}) for quantity {q_test}。")
                actual_stock = -2 # 表示發生了其他錯誤
                break # 無法確定庫存，跳出迴圈
        
        # 步驟 3: 確定最終庫存數量
        if actual_stock != -2: # 如果在搜尋過程中沒有發生其他嚴重錯誤
            actual_stock = max_addable_quantity_found
        
        if actual_stock >= 0:
            print(f"✅ 商品庫存數量為: {actual_stock}")
            if actual_stock > 0:
                print(f"{product_name} 目前有庫存！")
            else:
                print(f"{product_name} 目前無庫存。")
        else:
            print("🙁 無法獲取庫存數量，請檢查商品 Variant ID 或網站 API。")


    except requests.exceptions.RequestException as e:
        print(f"發生網路請求錯誤: {e}")
    except Exception as e:
        print(f"發生未知錯誤: {e}")
    finally:
        # 無論成功或失敗，都嘗試清理購物車，避免影響下次檢查
        try:
            print(f"清理購物車中的商品 ID: {variant_id}...")
            cart_api.remove_item(variant_id)
            print("購物車清理完成。")
        except requests.exceptions.RequestException as e:
            print(f"警告: 清理購物車時發生錯誤: {e}")
        except Exception as e:
            print(f"警告: 清理購物車時發生未知錯誤: {e}")


if __name__ == "__main__":
    monitored_products_data = []
    for url in PRODUCTS_URLS_TO_MONITOR:
        variant_id, product_id = get_ids_from_product_url(url)
        if variant_id and product_id:
            monitored_products_data.append({
                'name': f'商品 (URL: {url.split("/")[-1]})', # 使用 URL 最後一段作為商品名稱
                'variant_id': variant_id,
                'product_id': product_id
            })
        else:
            print(f"警告: 無法從網址 {url} 獲取商品 ID，將跳過此商品。")

    if not monitored_products_data:
        print("沒有可監控的商品。請檢查 PRODUCTS_URLS_TO_MONITOR 中的網址是否正確。")
    else:
        for product_info in monitored_products_data:
            check_product_stock(product_info)
