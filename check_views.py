import sys
sys.path.append('.')
from app.db.supabase import get_supabase_admin

try:
    sb = get_supabase_admin()
    # Try to select the specific post with views_count
    result = sb.table('news_posts').select('id, title, views_count').eq('id', '4ce52a51-13fe-4880-b397-6885d07891d4').single().execute()
    print('Post found:')
    print(f'ID: {result.data["id"]}')
    print(f'Title: {result.data["title"]}')
    print(f'Views: {result.data.get("views_count", "N/A")}')
except Exception as e:
    print(f'Error: {e}')