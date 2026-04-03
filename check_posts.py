import sys
sys.path.append('.')
from app.db.supabase import get_supabase_admin

try:
    sb = get_supabase_admin()
    result = sb.table('news_posts').select('*').execute()
    print(f'Found {len(result.data)} news posts:')
    for post in result.data:
        print(f'  ID: {post["id"]} - Title: {post["title"]}')
except Exception as e:
    print(f'Error: {e}')