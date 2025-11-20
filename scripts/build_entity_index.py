"""
Build Canonical Entity Index

This script:
1. Collects all entities from all 210 documents (startups, articles, github_repos)
2. Groups them by (entity_text + entity_type)
3. Counts mentions and tracks source documents
4. Saves to new 'canonical_entities' collection

Why we're doing this:
- Creates a searchable index of all entities
- Makes it easy to find "which documents mention X?"
- Prevents duplicate nodes in Neo4j graph
- Enables entity-based queries and statistics
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.mongo_client import MongoDBClient
import logging
from collections import defaultdict
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def collect_entities_from_collection(mongo, collection_name):
    """
    Collect all entities from a specific MongoDB collection

    Args:
        mongo: MongoDBClient instance
        collection_name: Name of collection ('startups', 'articles', 'github_repos')

    Returns:
        List of tuples: (entity_text, entity_type, doc_id, collection_name)

    Example return:
        [
            ('Suno', 'ORG', ObjectId('...'), 'startups'),
            ('Google', 'ORG', ObjectId('...'), 'articles'),
            ...
        ]
    """

    entity_mentions = []

    print(f"  Collecting from {collection_name}...")
    docs = list(mongo.db[collection_name].find({'entities': {'$exists': True}}))

    for doc in docs:
        doc_id = str(doc['_id']) 
        entities = doc.get('entities', [])

        for entity in entities:
            entity_mentions.append((
                entity['text'],
                entity['label'],
                doc_id,
                collection_name
            ))

    logger.info(f"Collected {len(entity_mentions)} entity mentions from {collection_name}")
    return entity_mentions


def build_entity_index(all_entity_mentions):
    """
    Group entities and count mentions

    Args:
        all_entity_mentions: List of tuples from collect_entities_from_collection

    Returns:
        Dictionary with entity index
        {
            ('Suno', 'ORG'): {
                'text': 'Suno',
                'type': 'ORG',
                'mention_count': 2,
                'mentioned_in': [
                    {'doc_id': '...', 'collection': 'startups'},
                    {'doc_id': '...', 'collection': 'startups'}
                ]
            },
            ...
        }
    """

    print("\n  Building entity index...")

    # Use defaultdict to automatically create entries
    entity_index = defaultdict(lambda: {
        'text': None,
        'type': None,
        'mention_count': 0,
        'mentioned_in': []
    })

    for entity_text, entity_type, doc_id, collection_name in all_entity_mentions:
        key = (entity_text, entity_type)
    
        # Set text and type (first time only)
        if entity_index[key]['text'] is None:
            entity_index[key]['text'] = entity_text
            entity_index[key]['type'] = entity_type
    
        # Increment count
        entity_index[key]['mention_count'] += 1
    
        # Add document reference
        entity_index[key]['mentioned_in'].append({
            'doc_id': doc_id,
            'collection': collection_name
        })

    logger.info(f"Created index for {len(entity_index)} unique entities")
    return entity_index


def save_to_mongodb(mongo, entity_index):
    """
    Save entity index to MongoDB 'canonical_entities' collection

    Args:
        mongo: MongoDBClient instance
        entity_index: Dictionary from build_entity_index()

    Returns:
        Number of entities saved
    """

    print("\n  Saving to MongoDB...")

    # Clear existing data (fresh start)
    mongo.db.canonical_entities.delete_many({})
    logger.info("Cleared existing canonical_entities collection")

    # Prepare documents for insertion
    entities_to_insert = []

    for (entity_text, entity_type), data in entity_index.items():
        entity_doc = {
            'entity_text': data['text'],
            'entity_type': data['type'],
            'mention_count': data['mention_count'],
            'mentioned_in': data['mentioned_in'],
            'created_at': datetime.utcnow().isoformat()
        }
        entities_to_insert.append(entity_doc)


    result = mongo.db.canonical_entities.insert_many(entities_to_insert)
    return len(result.inserted_ids)



def print_statistics(entity_index):
    """
    Print interesting statistics about the entities

    Args:
        entity_index: Dictionary from build_entity_index()
    """

    print("\n" + "=" * 70)
    print("ENTITY STATISTICS")
    print("=" * 70)

    # Count by entity type
    type_counts = defaultdict(int)
    for (_, entity_type), _ in entity_index.items():
        type_counts[entity_type] += 1

    print("\nEntities by type:")
    for entity_type, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {entity_type}: {count}")

    # Most mentioned entities
    print("\nTop 10 most-mentioned entities:")
    sorted_entities = sorted(
        entity_index.items(),
        key=lambda x: x[1]['mention_count'],
        reverse=True
    )

    for i, ((entity_text, entity_type), data) in enumerate(sorted_entities[:10], 1):
        print(f"  {i}. {entity_text} ({entity_type}): {data['mention_count']} mentions")


def main():
    """Main function to build entity index"""

    print("=" * 70)
    print("BUILD CANONICAL ENTITY INDEX")
    print("=" * 70)

    # Step 1: Connect to MongoDB
    print("\n[1] Connecting to MongoDB...")
    mongo = MongoDBClient()
    print("SUCCESS Connected\n")

    # Step 2: Collect entities from all collections
    print("[2] Collecting entities from all documents...")

    all_entity_mentions = []

    # Collect from startups
    startup_mentions = collect_entities_from_collection(mongo, 'startups')
    all_entity_mentions.extend(startup_mentions)

    # Collect from articles
    article_mentions = collect_entities_from_collection(mongo, 'articles')
    all_entity_mentions.extend(article_mentions)

    # Collect from github_repos
    repo_mentions = collect_entities_from_collection(mongo, 'github_repos')
    all_entity_mentions.extend(repo_mentions)

    print(f"\nTotal entity mentions collected: {len(all_entity_mentions)}")

    # Step 3: Build entity index
    print("\n[3] Building entity index...")
    entity_index = build_entity_index(all_entity_mentions)

    # Step 4: Save to MongoDB
    print("\n[4] Saving to canonical_entities collection...")
    saved_count = save_to_mongodb(mongo, entity_index)
    print(f"SUCCESS Saved {saved_count} unique entities")

    # Step 5: Print statistics
    print_statistics(entity_index)

    # Cleanup
    print("\n" + "=" * 70)
    print("SUCCESS Entity index built!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Check MongoDB Compass to see the 'canonical_entities' collection")
    print("2. You can now easily query: 'Which documents mention X?'")
    print("3. Ready for Sub-Phase 2.3 (Neo4j Schema Design)")

    mongo.close()


if __name__ == "__main__":
    main()
