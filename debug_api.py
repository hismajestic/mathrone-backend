import sys
sys.path.append('.')
from app.db.supabase import get_supabase_admin

try:
    sb = get_supabase_admin()
    # Try the update query that's failing
    print("Testing update query...")
    result = sb.table("news_posts").update({"views_count": sb.raw("views_count + 1")}).eq("id", "4ce52a51-13fe-4880-b397-6885d07891d4").execute()
    print("Update successful")

    # Now try to select the post
    print("Testing select query...")
    post = sb.table("news_posts").select("*").eq("id", "4ce52a51-13fe-4880-b397-6885d07891d4").single().execute().data
    print(f"Post found: {post['title']}")
    print(f"Views count: {post['views_count']}")

except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()