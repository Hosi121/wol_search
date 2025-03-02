import streamlit as st
import requests
from bs4 import BeautifulSoup
import urllib.parse
import pandas as pd
import time

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
        st.markdown("### About")
        st.markdown("""
        このアプリはWatchTower Online Libraryの検索を行います。
        キーワードを入力し、検索ボタンをクリックしてください。
        """)
        
        st.markdown("### Export")
        export_format = st.selectbox("エクスポート形式", ["CSV", "Excel"])
        
        # 検索結果がある場合のみエクスポートボタンを表示
        if 'all_results' in st.session_state and len(st.session_state.all_results) > 0:
            if st.button("検索結果をエクスポート", use_container_width=True):
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
                else:
                    output = pd.ExcelWriter(f"search_results_{keyword}_{lang}.xlsx", engine='xlsxwriter')
                    df.to_excel(output, index=False, sheet_name='検索結果')
                    output.save()
                    st.success("Excelファイルを保存しました。")

    # メインコンテンツエリア
    st.title("JW Library Search Tool")
    
    # 初期表示
    if 'all_results' not in st.session_state:
        st.session_state.all_results = []
    
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
    elif keyword and search_button:
        st.info("検索キーワードを入力し、検索ボタンを押してください。")

if __name__ == "__main__":
    main()
