"""
Remove duplicate documents from MongoDB collections
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.mongo_client import MongoDBClient


def remove_duplicates():
    """Remove duplicate documents from all collections"""

    mongo = MongoDBClient()

    try:
        print('=' * 70)
        print('REMOVING DUPLICATES')
        print('=' * 70)

        # 1. Remove duplicate startups (by name, keep most recent)
        print('\n1️⃣  Cleaning STARTUPS collection...')
        startups = list(mongo.db.startups.find().sort('scraped_at', -1))
        seen_names = set()
        to_delete = []

        for startup in startups:
            name = startup['name']
            if name in seen_names:
                to_delete.append(startup['_id'])
            else:
                seen_names.add(name)

        if to_delete:
            result = mongo.db.startups.delete_many({'_id': {'$in': to_delete}})
            print(f'   ✅ Removed {result.deleted_count} duplicate startups')
        else:
            print('   ✅ No duplicates found')

        # 2. Remove duplicate articles (by URL, keep most recent)
        print('\n2️⃣  Cleaning ARTICLES collection...')
        articles = list(mongo.db.articles.find().sort('scraped_at', -1))
        seen_urls = set()
        to_delete = []

        for article in articles:
            url = article.get('article_url', '')
            if url and url in seen_urls:
                to_delete.append(article['_id'])
            elif url:
                seen_urls.add(url)

        if to_delete:
            result = mongo.db.articles.delete_many({'_id': {'$in': to_delete}})
            print(f'   ✅ Removed {result.deleted_count} duplicate articles')
        else:
            print('   ✅ No duplicates found')

        # 3. Remove duplicate github repos (by full_name, keep most recent)
        print('\n3️⃣  Cleaning GITHUB_REPOS collection...')
        repos = list(mongo.db.github_repos.find().sort('scraped_at', -1))
        seen_repos = set()
        to_delete = []

        for repo in repos:
            full_name = repo['full_name']
            if full_name in seen_repos:
                to_delete.append(repo['_id'])
            else:
                seen_repos.add(full_name)

        if to_delete:
            result = mongo.db.github_repos.delete_many({'_id': {'$in': to_delete}})
            print(f'   ✅ Removed {result.deleted_count} duplicate repos')
        else:
            print('   ✅ No duplicates found')

        # Final count
        print('\n' + '=' * 70)
        print('FINAL COUNT AFTER CLEANUP')
        print('=' * 70)

        startups_count = mongo.db.startups.count_documents({})
        articles_count = mongo.db.articles.count_documents({})
        github_count = mongo.db.github_repos.count_documents({})

        print(f'\n📊 Collection Statistics:')
        print(f'   • startups:      {startups_count:3d} documents')
        print(f'   • articles:      {articles_count:3d} documents')
        print(f'   • github_repos:  {github_count:3d} documents')
        print(f'   ' + '-' * 40)
        print(f'   TOTAL:          {startups_count + articles_count + github_count:3d} unique documents')
        print()
        print('=' * 70)
        print('✅ Cleanup Complete! All duplicates removed.')
        print('=' * 70)

    finally:
        mongo.close()


if __name__ == '__main__':
    remove_duplicates()
