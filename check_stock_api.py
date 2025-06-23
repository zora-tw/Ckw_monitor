# check_stock_api.py
import requests
import json
import datetime
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

# 將最大數量調整為 999，避免觸發網站 API 的數量限制錯誤 (例如 422 錯誤)。
# 即使設置為 999，網站也會自動限制為實際庫存量。
MAX_QUANTITY = 300 

class CartAPI:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session()

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status() # 檢查請求是否成功，如果失敗則拋出異常
        return response

    def get_cart(self):
        response = self._request("GET", "/cart.js", headers={"accept": "*/*"})
        return response.json().get('items')

    def add_item(self, variant_id, product_id, quantity):
        data = {
            "form_type": "product",
            "utf8": "✓",
            "id": variant_id,
            "quantity": quantity,
            "product-id": product_id,
            "section-id": "template--18391309091057__main", # 此值可能需要根據網站實際情況調整
        }
        # requests 會自動處理 form-data 的 Content-Type
        response = self._request("POST", "/cart/add.js", data=data, headers={"X-Requested-With": "XMLHttpRequest"})
        return response.status_code

    def get_item_quantity_in_cart(self, variant_id):
        items = self.get_cart()
        if items:
            for item in items:
                if str(item.get('id')) == str(variant_id):
                    return item.get('quantity', -1)
        return -1

    def remove_item(self, variant_id):
        items = self.get_cart()
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
            self._request("POST", "/cart/change.js", json=payload, headers={"content-type": "application/json"})
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
    initial_quantity_in_cart = 0

    print(f"\n--- [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 檢查商品: {product_name} ---")

    try:
        # 步驟 1: 嘗試移除現有商品以確保購物車是乾淨的
        try:
            initial_quantity_in_cart = cart_api.remove_item(variant_id)
            if initial_quantity_in_cart > 0:
                print(f"已從購物車中移除了 {initial_quantity_in_cart} 個商品 ID: {variant_id} (檢查前清理)。")
        except requests.exceptions.RequestException as e:
            print(f"警告: 嘗試移除商品時發生錯誤 (可能購物車為空或網路問題): {e}")

        # 步驟 2: 嘗試將最大數量加入購物車
        print(f"嘗試將 {MAX_QUANTITY} 個商品 ID: {variant_id} 加入購物車...")
        add_status = cart_api.add_item(variant_id, product_id, MAX_QUANTITY)
        if 200 <= add_status < 300:
            print(f"成功發送加入購物車請求 (狀態碼: {add_status})。")
        else:
            # 如果還是發生 4xx 錯誤，請檢查錯誤訊息，可能是其他問題 (例如 section-id 不正確)
            print(f"錯誤: 加入購物車請求失敗 (狀態碼: {add_status})。")
            print("無法確定庫存，請檢查 BASE_URL 和商品 ID 是否正確，或網站是否更改了 API。")
            return

        # 步驟 3: 獲取實際加入的數量 (即庫存)
        stock_quantity = cart_api.get_item_quantity_in_cart(variant_id)

        if stock_quantity >= 0:
            print(f"✅ 商品庫存數量為: {stock_quantity}")
            if stock_quantity > 0:
                print(f"{product_name} 目前有庫存！")
            else:
                print(f"{product_name} 目前無庫存。")
        else:
            print("🙁 無法獲取庫存數量，請檢查商品 Variant ID 或網站 API。")

        # 步驟 4: 清理購物車
        print(f"清理購物車中的商品 ID: {variant_id}...")
        cart_api.remove_item(variant_id)
        print("購物車清理完成。")

    except requests.exceptions.RequestException as e:
        print(f"發生網路請求錯誤: {e}")
    except Exception as e:
        print(f"發生未知錯誤: {e}")

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
