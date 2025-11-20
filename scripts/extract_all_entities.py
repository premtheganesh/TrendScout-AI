"""
Extract Entities from All MongoDB Documents

This script:
1. Reads all documents from MongoDB (startups, articles, github_repos)
2. Extracts entities from text fields using spaCy
3. Saves extracted entities back to MongoDB

Why we're doing this:
- Add structured entity data to all documents
- Prepare data for Neo4j knowledge graph building
- Enable entity-based queries and analysis
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.extractors.entity_extractor import EntityExtractor
from src.database.mongo_client import MongoDBClient
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# TEST_MODE: Set to True for testing on small batch, False for all documents
TEST_MODE = False  # <- Change to False when ready to process all 210 docs

# Batch sizes for testing
TEST_LIMITS = {
    'startups': 10,      # Process 10 startups in test mode
    'articles': 5,       # Process 5 articles in test mode
    'github_repos': 5    # Process 5 repos in test mode
}


def process_startups(extractor, mongo, test_mode=True):
    """
    Process startup documents and extract entities

    Args:
        extractor: EntityExtractor instance
        mongo: MongoDBClient instance
        test_mode: If True, only process a small batch

    Returns:
        Dict with statistics (processed, entities_found, errors)
    """

    print("\n" + "=" * 70)
    print("PROCESSING STARTUPS COLLECTION")
    print("=" * 70)

    # Get documents
    if test_mode:
        limit = TEST_LIMITS['startups']
        startups = list(mongo.db.startups.find().limit(limit))
        print(f"TEST MODE: Processing {limit} startups")
    else:
        startups = list(mongo.db.startups.find())
        print(f"PRODUCTION MODE: Processing all {len(startups)} startups")

    stats = {'processed': 0, 'entities_found': 0, 'errors': 0}

    for i, startup in enumerate(startups, 1):
        startup_name = startup.get('name', 'Unknown')

        try:
            # Get description text
            description = startup.get('description', '')

            if not description:
                logger.warning(f"No description for {startup_name}, skipping")
                continue

            # Extract entities
            entities = extractor.extract_entities(description)

            mongo.db.startups.update_one(
                {'_id': startup['_id']},           # Find this document
                {'$set': {                          # Set these fields
                    'entities': entities,
                    'entities_extracted_at': datetime.utcnow().isoformat()
                }}
            )

            # Update statistics
            stats['processed'] += 1
            stats['entities_found'] += len(entities)

            # Show progress every 10 documents
            if i % 10 == 0:
                print(f"  Processed {i}/{len(startups)} startups...")

            logger.info(f"Processed {startup_name}: {len(entities)} entities")

        except Exception as e:
            logger.error(f"Error processing {startup_name}: {e}")
            stats['errors'] += 1

    print(f"\nStartups Summary:")
    print(f"  Processed: {stats['processed']}")
    print(f"  Total entities: {stats['entities_found']}")
    print(f"  Errors: {stats['errors']}")

    return stats


def process_articles(extractor, mongo, test_mode=True):
    """
    Process article documents and extract entities

    Args:
        extractor: EntityExtractor instance
        mongo: MongoDBClient instance
        test_mode: If True, only process a small batch

    Returns:
        Dict with statistics
    """

    print("\n" + "=" * 70)
    print("PROCESSING ARTICLES COLLECTION")
    print("=" * 70)

    # Get documents
    if test_mode:
        limit = TEST_LIMITS['articles']
        articles = list(mongo.db.articles.find().limit(limit))
        print(f"TEST MODE: Processing {limit} articles")
    else:
        articles = list(mongo.db.articles.find())
        print(f"PRODUCTION MODE: Processing all {len(articles)} articles")

    stats = {'processed': 0, 'entities_found': 0, 'errors': 0}

    for i, article in enumerate(articles, 1):
        article_title = article.get('title', 'Unknown')[:50]  # First 50 chars

        try:
            # Get article text (might be in 'description' or 'content' field)
            text = article.get('description', '') or article.get('content', '')

            if not text:
                logger.warning(f"No text for article '{article_title}...', skipping")
                continue

            # Extract entities
            entities = extractor.extract_entities(text)
            
            mongo.db.articles.update_one(
                {'_id': article['_id']},
                {'$set': {
                    'entities': entities,
                    'entities_extracted_at': datetime.utcnow().isoformat()
                }}
            )


            # Update statistics
            stats['processed'] += 1
            stats['entities_found'] += len(entities)

            logger.info(f"Processed article: {len(entities)} entities")

        except Exception as e:
            logger.error(f"Error processing article '{article_title}...': {e}")
            stats['errors'] += 1

    print(f"\nArticles Summary:")
    print(f"  Processed: {stats['processed']}")
    print(f"  Total entities: {stats['entities_found']}")
    print(f"  Errors: {stats['errors']}")

    return stats


def process_github_repos(extractor, mongo, test_mode=True):
    """
    Process GitHub repo documents and extract entities

    Args:
        extractor: EntityExtractor instance
        mongo: MongoDBClient instance
        test_mode: If True, only process a small batch

    Returns:
        Dict with statistics
    """

    print("\n" + "=" * 70)
    print("PROCESSING GITHUB_REPOS COLLECTION")
    print("=" * 70)

    # Get documents
    if test_mode:
        limit = TEST_LIMITS['github_repos']
        repos = list(mongo.db.github_repos.find().limit(limit))
        print(f"TEST MODE: Processing {limit} repos")
    else:
        repos = list(mongo.db.github_repos.find())
        print(f"PRODUCTION MODE: Processing all {len(repos)} repos")

    stats = {'processed': 0, 'entities_found': 0, 'errors': 0}

    for i, repo in enumerate(repos, 1):
        repo_name = repo.get('full_name', 'Unknown')

        try:
            # Get repo description
            description = repo.get('description', '')

            if not description or description == 'No description':
                logger.warning(f"No description for {repo_name}, skipping")
                continue

            # Extract entities
            entities = extractor.extract_entities(description)

            mongo.db.github_repos.update_one(
                {'_id': repo['_id']},
                {'$set': {
                    'entities': entities,
                    'entities_extracted_at': datetime.utcnow().isoformat()
                }}
            )

            # Update statistics
            stats['processed'] += 1
            stats['entities_found'] += len(entities)

            logger.info(f"Processed {repo_name}: {len(entities)} entities")

        except Exception as e:
            logger.error(f"Error processing {repo_name}: {e}")
            stats['errors'] += 1

    print(f"\nGitHub Repos Summary:")
    print(f"  Processed: {stats['processed']}")
    print(f"  Total entities: {stats['entities_found']}")
    print(f"  Errors: {stats['errors']}")

    return stats


def main():
    """Main function to extract entities from all collections"""

    print("=" * 70)
    print("ENTITY EXTRACTION - BATCH PROCESSING")
    print("=" * 70)

    if TEST_MODE:
        print("\nMODE: TEST (processing small batch)")
        print(f"  - Startups: {TEST_LIMITS['startups']}")
        print(f"  - Articles: {TEST_LIMITS['articles']}")
        print(f"  - GitHub repos: {TEST_LIMITS['github_repos']}")
    else:
        print("\nMODE: PRODUCTION (processing all documents)")

    print()

    # Step 1: Create EntityExtractor
    print("[1] Creating EntityExtractor...")
    extractor = EntityExtractor()
    print("SUCCESS EntityExtractor created\n")

    # Step 2: Connect to MongoDB
    print("[2] Connecting to MongoDB...")
    mongo = MongoDBClient()
    print("SUCCESS Connected to MongoDB\n")

    # Step 3: Process all collections
    start_time = datetime.now()

    startup_stats = process_startups(extractor, mongo, test_mode=TEST_MODE)
    article_stats = process_articles(extractor, mongo, test_mode=TEST_MODE)
    repo_stats = process_github_repos(extractor, mongo, test_mode=TEST_MODE)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Step 4: Final summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)

    total_processed = (startup_stats['processed'] +
                       article_stats['processed'] +
                       repo_stats['processed'])

    total_entities = (startup_stats['entities_found'] +
                      article_stats['entities_found'] +
                      repo_stats['entities_found'])

    total_errors = (startup_stats['errors'] +
                    article_stats['errors'] +
                    repo_stats['errors'])

    print(f"\nDocuments processed: {total_processed}")
    print(f"Total entities extracted: {total_entities}")
    print(f"Errors: {total_errors}")
    print(f"Time taken: {duration:.2f} seconds")

    if TEST_MODE:
        print("\n" + "=" * 70)
        print("NEXT STEP:")
        print("=" * 70)
        print("1. Check MongoDB to verify 'entities' field was added")
        print("2. If it looks good, set TEST_MODE = False in this script")
        print("3. Run again to process all 210 documents")

    # Cleanup
    mongo.close()


if __name__ == "__main__":
    main()