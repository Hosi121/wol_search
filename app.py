import streamlit as st
import requests
from bs4 import BeautifulSoup
import urllib.parse
import pandas as pd
import time
import io
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ページ設定
st.set_page_config(
    page_title="JW Library Search",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# カスタムCSS
st.markdown("""
<style>
    .main {
        background-color: #f8f9fa;
    }
    .stApp {
        font-family: 'Roboto', sans-serif;
    }
    .search-result {
        background-color: white;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 15px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        transition: transform 0.2s;
    }
    .search-result:hover {
        transform: translateY(-3px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
    }
    .result-title {
        color: #1f77b4;
        font-weight: bold;
        font-size: 18px;
        margin-bottom: 5px;
    }
    .result-publication {
        color: #777;
        font-size: 14px;
        font-style: italic;
        margin-bottom: 8px;
    }
    .result-snippet {
        color: #333;
        font-size: 15px;
        line-height: 1.5;
    }
    .placeholder {
        background: linear-gradient(90deg, #f2f2f2 25%, #e6e6e6 50%, #f2f2f2 75%);
        background-size: 200% 100%;
        animation: loading 1.5s infinite;
        border-radius: 4px;
        height: 100px;
        margin-bottom: 15px;
    }
    @keyframes loading {
        0% {
            background-position: 200% 0;
        }
        100% {
            background-position: -200% 0;
        }
    }
    .sidebar-header {
        margin-bottom: 30px;
    }
    .google-sheet-section {
        background-color: #f0f7ff;
        border-radius: 10px;
        padding: 15px;
        margin-top: 20px;
        border-left: 5px solid #4285F4;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------
# ① 言語に合わせたベースURLの設定
# ------------------------------
def get_base_url(lang):
    """
    言語ごとにベースURLを返します。
    日本語の場合: "https://wol.jw.org/ja/wol/s/r7/lp-j"
    英語の場合:   "https://wol.jw.org/en/wol/s/r1/lp-e"
    """
    urls = {
        "ja": "https://wol.jw.org/ja/wol/s/r7/lp-j",
        "en": "https://wol.jw.org/en/wol/s/r1/lp-e"
    }
    # 指定された言語が無い場合は日本語版を返す
    return urls.get(lang, urls["ja"])

# ------------------------------
# ② 検索処理（ページ単位でyield）
# ------------------------------
def _fetch_and_parse_page(keyword, page_num, lang="ja", sort="occ"):
    """
    キーワード、ページ番号、言語、ソート順でリクエストし、
    結果（タイトル／リンク／スニペット／出版物情報）のリストと次ページの有無を返します。
    """
    base_url = get_base_url(lang)
    params = {
        "q": keyword,
        "st": "a",
        "p": "par",
        "r": sort,
        "pg": str(page_num),
    }
    
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        items = []
        # 旧形式の場合（ul.results.resultContentDocument）
        result_blocks = soup.select("ul.results.resultContentDocument")
        # カード形式の場合は li.navCard を対象
        if not result_blocks:
            result_blocks = soup.select("li.navCard")
        
        for rb in result_blocks:
            # 【ケース1】旧形式
            caption_li = rb.select_one("li.caption")
            if caption_li:
                link_tag = caption_li.select_one("a.lnk")
                if link_tag:
                    title = link_tag.get_text(strip=True)
                    # 相対パスを絶対URLに変換
                    link = urllib.parse.urljoin(base_url, link_tag.get("href", "").strip())
                else:
                    title, link = "", ""
                snippet_li = rb.select_one("li.searchResult")
                if snippet_li:
                    doc_div = snippet_li.select_one("div.document")
                    snippet = doc_div.get_text(" ", strip=True) if doc_div else ""
                else:
                    snippet = ""
                publication = ""
            # 【ケース2】カード形式
            elif rb.select_one("div.cardTitleBlock"):
                title_div = rb.select_one("div.cardLine1")
                title = title_div.get_text(strip=True) if title_div else ""
                alt_title_div = rb.select_one("div.cardLine2")
                if not title and alt_title_div:
                    title = alt_title_div.get_text(strip=True)
                link_tag = rb.select_one("a")
                if link_tag:
                    link = urllib.parse.urljoin(base_url, link_tag.get("href", "").strip())
                else:
                    link = ""
                snippet = ""
                detail_div = rb.select_one("div.cardTitleDetail")
                publication = detail_div.get_text(strip=True) if detail_div else ""
            else:
                title, link, snippet, publication = "", "", "", ""
            
            if title and link:  # 有効な結果のみ追加
                items.append({
                    "title": title,
                    "link": link,
                    "snippet": snippet,
                    "publication": publication
                })
        
        # ページネーション情報の取得（該当要素が無ければ次ページ無しと判断）
        try:
            total_str = soup.select_one("#searchResultsTotal")["value"]
            page_size_str = soup.select_one("#searchResultsPageSize")["value"]
            current_page_str = soup.select_one("#searchResultsPageNumber")["value"]
            total = int(total_str)
            page_size = int(page_size_str)
            current_page = int(current_page_str)
            total_pages = (total + page_size - 1) // page_size
            has_next = (current_page < total_pages)
            result_info = {
                "total": total,
                "current_page": current_page,
                "total_pages": total_pages
            }
        except (TypeError, KeyError):
            has_next = False
            result_info = {
                "total": len(items),
                "current_page": 1,
                "total_pages": 1
            }
        
        return {"items": items, "has_next": has_next, "result_info": result_info}
    
    except Exception as e:
        st.error(f"検索中にエラーが発生しました: {str(e)}")
        return {"items": [], "has_next": False, "result_info": {"total": 0, "current_page": 1, "total_pages": 1}}

# ------------------------------
# Google Sheets 連携機能
# ------------------------------
def connect_to_google_sheets(json_key_content):
    """
    Google SheetsへのAPI接続
    """
    try:
        # 認証情報をJSONから読み込む
        credentials = service_account.Credentials.from_service_account_info(
            json_key_content,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        
        # Google Sheets APIクライアントを作成
        gc = gspread.authorize(credentials)
        sheets_api = build('sheets', 'v4', credentials=credentials)
        
        return gc, sheets_api
    except Exception as e:
        st.error(f"Google Sheetsへの接続に失敗しました: {str(e)}")
        return None, None

def get_or_create_sheet(gc, sheet_name, worksheet_name=None):
    """
    指定したシートを取得するか、存在しない場合は新規作成します
    """
    try:
        # シートが存在するか確認
        try:
            sh = gc.open(sheet_name)
        except gspread.exceptions.SpreadsheetNotFound:
            # シートが存在しない場合は新規作成
            sh = gc.create(sheet_name)
            # 作成者に編集権限を付与
            sh.share(gc.auth.service_account_email, role='writer', perm_type='user')
        
        # ワークシートを取得または作成
        if worksheet_name:
            try:
                worksheet = sh.worksheet(worksheet_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=worksheet_name, rows=100, cols=20)
        else:
            worksheet = sh.sheet1
        
        return sh, worksheet
    except Exception as e:
        st.error(f"シートの取得または作成に失敗しました: {str(e)}")
        return None, None

def export_to_google_sheets(gc, data, sheet_name, worksheet_name=None):
    """
    検索結果をGoogle Sheetsに出力します
    """
    try:
        # シートを取得または作成
        sh, worksheet = get_or_create_sheet(gc, sheet_name, worksheet_name)
        if not sh or not worksheet:
            return False, "シートの準備に失敗しました"
        
        # データを整形
        df = pd.DataFrame(data)
        headers = df.columns.tolist()
        values = [headers] + df.values.tolist()
        
        # シートをクリアしてデータを書き込み
        worksheet.clear()
        worksheet.update(values)
        
        # 表示の調整
        worksheet.format('A1:Z1', {
            "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
            "horizontalAlignment": "CENTER",
            "textFormat": {"bold": True}
        })
        
        return True, f"データをシート '{sheet_name} / {worksheet.title}' に正常にエクスポートしました"
    except Exception as e:
        return False, f"Google Sheetsへのエクスポートに失敗しました: {str(e)}"

# ------------------------------
# Streamlit UI処理
# ------------------------------
def display_search_result(item):
    """検索結果の1項目を表示する"""
    st.markdown(f"""
    <div class="search-result">
        <div class="result-title">{item['title']}</div>
        <div class="result-publication">{item['publication']}</div>
        <div class="result-snippet">{item['snippet']}</div>
        <a href="{item['link']}" target="_blank">記事を読む</a>
    </div>
    """, unsafe_allow_html=True)

def display_loading_animation(num_placeholders=3):
    """ローディングプレースホルダーを表示"""
    loading_container = st.container()
    with loading_container:
        for _ in range(num_placeholders):
            st.markdown('<div class="placeholder"></div>', unsafe_allow_html=True)
    return loading_container

# ------------------------------
# Streamlitアプリのメイン部分
# ------------------------------
def main():
    # セッション状態の初期化
    if 'google_sheets_connected' not in st.session_state:
        st.session_state.google_sheets_connected = False
    if 'gc' not in st.session_state:
        st.session_state.gc = None
    if 'all_results' not in st.session_state:
        st.session_state.all_results = []
        
    # サイドバー
    with st.sidebar:
        st.markdown('<div class="sidebar-header"></div>', unsafe_allow_html=True)
        st.image("https://assetsnffrgf-a.akamaihd.net/assets/m/802013135/univ/art/802013135_univ_lsr_xl.jpg", width=200)
        st.markdown("## JW Library Search")
        st.markdown("---")
        
        # 検索設定
        keyword = st.text_input("検索キーワード", placeholder="例: 聖書, 信仰, 希望...")
        lang = st.selectbox("言語を選択", ["ja", "en"], format_func=lambda x: "日本語" if x == "ja" else "English")
        sort_options = {
            "newest": "最新順",
            "occ": "関連性順"
        }
        sort = st.selectbox("並び順", list(sort_options.keys()), format_func=lambda x: sort_options[x])
        max_pages = st.slider("最大取得ページ数", 1, 10, 3)
        
        search_button = st.button("検索", use_container_width=True)
        
        st.markdown("---")
        st.markdown("### エクスポート")
        
        # ローカルにダウンロード
        if 'all_results' in st.session_state and len(st.session_state.all_results) > 0:
            export_format = st.selectbox("エクスポート形式", ["CSV", "Excel"])
            
            if st.button("検索結果をダウンロード", use_container_width=True):
                df = pd.DataFrame(st.session_state.all_results)
                
                if export_format == "CSV":
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="CSVをダウンロード",
                        data=csv,
                        file_name=f"search_results_{keyword}_{lang}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                else:  # Excel
                    # Excelデータをバイナリストリームとして作成
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                        df.to_excel(writer, index=False, sheet_name='検索結果')
                    
                    # バイナリデータをリセットして読み取り
                    output.seek(0)
                    excel_data = output.read()
                    
                    # ダウンロードボタン
                    st.download_button(
                        label="Excelをダウンロード",
                        data=excel_data,
                        file_name=f"search_results_{keyword}_{lang}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

        # Google Sheets連携
        st.markdown("---")
        with st.expander("Google Sheets連携", expanded=False):
            if not st.session_state.google_sheets_connected:
                st.markdown("### Google Sheetsに接続")
                st.markdown("""
                1. Google Cloud Consoleでサービスアカウントを作成
                2. サービスアカウントのJSONキーを取得
                3. JSONキーの内容を以下に貼り付け
                """)
                json_key = st.text_area("サービスアカウントのJSONキー", height=100, 
                                     placeholder='{  "type": "service_account",  "project_id": "...",  ... }')
                
                if st.button("接続", key="connect_google"):
                    try:
                        # JSONの構文チェック
                        import json
                        json_key_content = json.loads(json_key)
                        
                        # Google Sheetsに接続
                        gc, sheets_api = connect_to_google_sheets(json_key_content)
                        if gc and sheets_api:
                            st.session_state.gc = gc
                            st.session_state.sheets_api = sheets_api
                            st.session_state.google_sheets_connected = True
                            st.success("Google Sheetsに正常に接続しました！")
                    except json.JSONDecodeError:
                        st.error("JSONキーの形式が正しくありません。正確なJSONを貼り付けてください。")
                    except Exception as e:
                        st.error(f"接続エラー: {str(e)}")
            else:
                st.success("Google Sheetsに接続済みです")
                
                if 'all_results' in st.session_state and len(st.session_state.all_results) > 0:
                    st.markdown("### Google Sheetsにエクスポート")
                    sheet_name = st.text_input("スプレッドシート名", "JW検索結果")
                    worksheet_name = st.text_input("ワークシート名", "検索結果")
                    
                    if st.button("Google Sheetsにエクスポート", key="export_google"):
                        success, message = export_to_google_sheets(
                            st.session_state.gc, 
                            st.session_state.all_results, 
                            sheet_name, 
                            worksheet_name
                        )
                        if success:
                            st.success(message)
                        else:
                            st.error(message)
                
                if st.button("接続を解除", key="disconnect_google"):
                    st.session_state.gc = None
                    st.session_state.sheets_api = None
                    st.session_state.google_sheets_connected = False
                    st.info("Google Sheetsとの接続を解除しました")

    # メインコンテンツエリア
    st.title("JW Library Search Tool")
    
    # 検索実行
    if search_button and keyword:
        st.session_state.all_results = []  # 結果をリセット
        
        # 検索開始メッセージ
        st.info(f"キーワード「{keyword}」で検索を開始します...")
        
        # ローディングアニメーション表示
        loading = display_loading_animation()
        
        # 検索実行
        page_num = 1
        total_pages = max_pages  # デフォルト値
        
        while page_num <= max_pages:
            # 検索を実行
            page_data = _fetch_and_parse_page(keyword, page_num, lang=lang, sort=sort)
            
            # 結果を保存
            st.session_state.all_results.extend(page_data["items"])
            
            # 合計ページ数を更新
            if page_num == 1:
                total_pages = min(max_pages, page_data["result_info"]["total_pages"])
                if total_pages == 0:
                    break
            
            # 進捗状況を表示
            progress = page_num / total_pages
            st.progress(progress)
            
            # 次のページがなければ終了
            if not page_data["has_next"]:
                break
                
            page_num += 1
            time.sleep(0.5)  # サーバー負荷を考慮

        # ローディングを非表示
        loading.empty()
        
        # 検索結果概要
        if len(st.session_state.all_results) > 0:
            st.success(f"検索完了！ {len(st.session_state.all_results)} 件の結果が見つかりました。")
        else:
            st.warning("検索結果が見つかりませんでした。別のキーワードをお試しください。")
    
    # 検索結果の表示
    if 'all_results' in st.session_state and len(st.session_state.all_results) > 0:
        # 結果リストをDataFrameに変換
        df = pd.DataFrame(st.session_state.all_results)
        
        # タブで表示方法を切り替え
        tab1, tab2 = st.tabs(["カード表示", "テーブル表示"])
        
        with tab1:
            # カード表示
            for item in st.session_state.all_results:
                display_search_result(item)
        
        with tab2:
            # テーブル表示
            st.dataframe(
                df[["title", "publication", "link"]],
                column_config={
                    "title": "タイトル",
                    "publication": "出版物",
                    "link": st.column_config.LinkColumn("リンク")
                },
                hide_index=True,
                use_container_width=True
            )
    elif not keyword:
        st.info("検索キーワードを入力し、検索ボタンを押してください。")

if __name__ == "__main__":
    main()