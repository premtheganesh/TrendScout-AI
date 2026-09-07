"""Check all MongoDB collections and their contents"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.mongo_client import MongoDBClient


def check_collections():
    """Check all collections in MongoDB"""

    mongo = MongoDBClient()

    try:
        print('=' * 70)
        print('MONGODB COLLECTIONS CHECK')
        print('=' * 70)

        # List all collections in the database
        collections = mongo.db.list_collection_names()
        print(f'\n Collections in trendscout_ai database:')
        for col in collections:
            count = mongo.db[col].count_documents({})
            print(f'   • {col}: {count} documents')

        print('\n' + '=' * 70)
        print('DETAILED BREAKDOWN')
        print('=' * 70)

        # Show sample from each collection
        print('\n1⃣ STARTUPS collection:')
        startup_sample = mongo.db.startups.find_one()
        if startup_sample:
            print(f'   Sample: {startup_sample.get("name")} (source: {startup_sample.get("source")})')

            # Count by source
            sources = list(mongo.db.startups.aggregate([
                {'$group': {'_id': '$source', 'count': {'$sum': 1}}}
            ]))
            print('   By source:')
            for s in sources:
                print(f'      • {s["_id"]}: {s["count"]} companies')
        else:
            print('Collection is empty!')

        print('\n2⃣ ARTICLES collection:')
        article_sample = mongo.db.articles.find_one()
        if article_sample:
            title = article_sample.get('title', 'No title')
            print(f'   Sample: {title[:60]}...')
            print(f'   Source: {article_sample.get("source")}')
            total = mongo.db.articles.count_documents({})
            print(f'   Total: {total} articles')
        else:
            print('Collection is empty!')

        print('\n3⃣ GITHUB_REPOS collection:')
        repo_sample = mongo.db.github_repos.find_one()
        if repo_sample:
            print(f'Sample: {repo_sample.get("full_name")} ({repo_sample.get("stars")} )')
            print(f'   Source: {repo_sample.get("source")}')
            total = mongo.db.github_repos.count_documents({})
            print(f'   Total: {total} repos')
        else:
            print('Collection is empty!')

        print('\n' + '=' * 70)
        print('MONGODB COMPASS TIPS')
        print('=' * 70)
        print('\nTo view all collections in MongoDB Compass:')
        print('1. Open MongoDB Compass')
        print('2. Connect to: mongodb://localhost:27017')
        print('3. Click on database: trendscout_ai')
        print('4. You should see 3 collections:')
        print('   • startups (140 docs)')
        print('   • articles (20 docs)')
        print('   • github_repos (50 docs)')
        print()

    finally:
        mongo.close()


if __name__ == '__main__':
    check_collections()
