# check_stock_api.py
import requests
import json # 用於處理 JSON 數據

# --- 請在此處替換為您的實際資訊 ---
BASE_URL = 'https://chiikawamarket.jp' # 目標網站的根網址，例如：'https://chiikawamarket.jp'

# 您要監控的特定商品的 Variant ID 和 Product ID。
# 如何找到這些 ID：打開目標商品頁面，開啟瀏覽器開發者工具 (F12)，
# 在 Network (網路) 分頁下，點擊「加入購物車」按鈕，
# 觀察向 `/cart/add.js` 發送的 POST 請求的 "Payload" (負載) 或 "Form Data" 部分。
TARGET_VARIANT_ID = 'YOUR_VARIANT_ID_HERE'    # 例如：'42562479577265'
TARGET_PRODUCT_ID = 'YOUR_PRODUCT_ID_HERE' # 例如：'7692255748273'
# --- 替換結束 ---

MAX_QUANTITY = 1000000

class CartAPI:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session() # 使用 Session 可以自動處理 Cookies

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status() # 如果請求失敗 (狀態碼非 2xx)，則拋出異常
        return response

    def get_cart(self):
        response = self._request("GET", "/cart.js", headers={"accept": "*/*"})
        return response.json().get('items')

    def add_item(self, variant_id, product_id, quantity):
        # 根據原始 JS 腳本的 form-data 格式構建數據
        data = {
            "form_type": "product",
            "utf8": "✓",
            "id": variant_id,
            "quantity": quantity,
            "product-id": product_id,
            "section-id": "template--18391309091057__main", # 這個可能需要根據目標網站的實際情況調整
        }
        # requests 會自動處理 form-data 的 Content-Type
        response = self._request("POST", "/cart/add.js", data=data, headers={"X-Requested-With": "XMLHttpRequest"})
        return response.status_code

    def get_item_quantity_in_cart(self, variant_id):
        items = self.get_cart()
        if items:
            for item in items:
                if str(item.get('id')) == str(variant_id): # 確保類型匹配
                    return item.get('quantity', -1)
        return -1

    def remove_item(self, variant_id):
        items = self.get_cart()
        if not items:
            return 0

        # 找到商品在購物車中的行數 (line number)，從 1 開始
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
            return current_quantity # 返回移除的數量
        return 0

def check_product_stock(variant_id, product_id):
    cart_api = CartAPI(BASE_URL)
    initial_quantity_in_cart = 0

    print(f"[{requests.utils.to_native_string(requests.utils.datetime.now())}] 開始檢查商品 Variant ID: {variant_id}, Product ID: {product_id} 的庫存...")

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
            print(f"錯誤: 加入購物車請求失敗 (狀態碼: {add_status})。")
            print("無法確定庫存，請檢查 BASE_URL 和商品 ID 是否正確，或網站是否更改了 API。")
            return

        # 步驟 3: 獲取實際加入的數量 (即庫存)
        stock_quantity = cart_api.get_item_quantity_in_cart(variant_id)

        if stock_quantity >= 0:
            print(f"✅ 商品庫存數量為: {stock_quantity}")
            if stock_quantity > 0:
                print("--- 商品目前有庫存！---")
            else:
                print("--- 商品目前無庫存。---")
        else:
            print("🙁 無法獲取庫存數量，請檢查商品 Variant ID 或網站 API。")

        # 步驟 4: 清理購物車
        print(f"清理購物車中的商品 ID: {variant_id}...")
        cart_api.remove_item(variant_id)
        print("購物車清理完成。")

        # 步驟 5: (可選) 恢復檢查前購物車的狀態
        # 如果您希望每次檢查後，購物車內容能恢復到檢查前的狀態，可以保留這段。
        # 對於定時監控，通常不恢復是更簡潔的做法。
        # if initial_quantity_in_cart > 0:
        #     print(f"嘗試恢復 {initial_quantity_in_cart} 個商品 ID: {variant_id} 到購物車...")
        #     try:
        #         cart_api.add_item(variant_id, product_id, initial_quantity_in_cart)
        #         print('購物車狀態已恢復。')
        #     except requests.exceptions.RequestException as e:
        #         print(f"警告: 恢復購物車時發生錯誤: {e}")

    except requests.exceptions.RequestException as e:
        print(f"發生網路請求錯誤: {e}")
    except Exception as e:
        print(f"發生未知錯誤: {e}")

if __name__ == "__main__":
    check_product_stock(TARGET_VARIANT_ID, TARGET_PRODUCT_ID)
