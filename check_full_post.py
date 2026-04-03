import sys
sys.path.append('.')
from app.db.supabase import get_supabase_admin

try:
    sb = get_supabase_admin()
    # Check all columns of the post
    result = sb.table('news_posts').select('*').eq('id', '4ce52a51-13fe-4880-b397-6885d07891d4').single().execute()
    print('Full post data:')
    for key, value in result.data.items():
        print(f'  {key}: {value}')
except Exception as e:
    print(f'Error: {e}')