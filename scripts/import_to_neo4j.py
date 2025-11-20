"""
Import Data from MongoDB to Neo4j (ETL Script)

This script performs ETL (Extract, Transform, Load):
1. EXTRACT - Read data from MongoDB
2. TRANSFORM - Convert to Neo4j format
3. LOAD - Insert into Neo4j graph database

What gets imported:
- 251 Entity nodes
- 140 Startup nodes (with ALL fields)
- 20 Article nodes (with ALL fields)
- 50 GitHubRepo nodes (with ALL fields)
- MENTIONS relationships connecting them

Why we're doing this:
- Enable graph queries like "which startups mention Google?"
- Discover connections between entities
- Fast lookups using Neo4j indexes
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.mongo_client import MongoDBClient
from src.database.neo4j_client import Neo4jClient
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Batch size for processing (how many nodes to create at once)
BATCH_SIZE = 100


def import_entities(mongo, neo4j):
    """
    Import Entity nodes from MongoDB canonical_entities collection

    Process:
    1. Read all entities from MongoDB
    2. Transform to Neo4j format
    3. Use MERGE to create unique nodes
    4. Use batch processing for speed

    Cypher query explanation:
        UNWIND $batch AS entity      - Loop through batch list
        MERGE (e:Entity {...})        - Create node if doesn't exist (uses constraint)
        SET e.mention_count = ...     - Update properties
    """

    print("\n" + "=" * 70)
    print("IMPORTING ENTITIES")
    print("=" * 70)

    # EXTRACT: Read from MongoDB
    print("\n[1] Reading entities from MongoDB...")
    entities = list(mongo.db.canonical_entities.find())
    print(f"Found {len(entities)} entities")

    if len(entities) == 0:
        print("WARNING No entities found. Run build_entity_index.py first!")
        return 0

    # TRANSFORM: Convert MongoDB docs to Neo4j format
    print("\n[2] Transforming data for Neo4j...")
    entity_batch = []

    for entity in entities:
        # Convert MongoDB document to dictionary for Neo4j
        entity_data = {
            'entity_text': entity['entity_text'],
            'entity_type': entity['entity_type'],
            'mention_count': entity['mention_count']
        }
        entity_batch.append(entity_data)

    # LOAD: Insert into Neo4j using batch processing
    print(f"\n[3] Creating {len(entity_batch)} Entity nodes in Neo4j...")

    # Cypher query - MERGE ensures uniqueness using constraint we created
    query = """
    UNWIND $batch AS entity
    MERGE (e:Entity {
        entity_text: entity.entity_text,
        entity_type: entity.entity_type
    })
    SET e.mention_count = entity.mention_count
    """

    neo4j.run_write_query(query, {'batch': entity_batch})

    logger.info(f"Created {len(entity_batch)} Entity nodes")
    return len(entity_batch)


def import_startups(mongo, neo4j):
    """
    Import Startup nodes from MongoDB startups collection

    This imports ALL fields from MongoDB:
    - name, description, location, funding_amount, founded_date, website, source
    - Any other fields in your startup documents

    Why we include all fields:
    - Rich data for queries
    - Can filter by location, funding, etc.
    - Preserve all information from scraping
    """

    print("\n" + "=" * 70)
    print("IMPORTING STARTUPS")
    print("=" * 70)

    # EXTRACT: Read from MongoDB
    print("\n[1] Reading startups from MongoDB...")
    startups = list(mongo.db.startups.find())
    print(f"Found {len(startups)} startups")

    if len(startups) == 0:
        print("WARNING No startups found!")
        return 0

    # TRANSFORM: Convert to Neo4j format
    print("\n[2] Transforming startup data...")
    startup_batch = []

    for startup in startups:
        # Convert MongoDB _id to string (Neo4j can't handle ObjectId)
        startup_data = {
            'startup_id': str(startup['_id']),
            'name': startup.get('name', ''),
            'description': startup.get('description', ''),
            'location': startup.get('location', ''),
            'funding_amount': startup.get('funding_amount', ''),
            'founded_date': startup.get('founded_date', ''),
            'website': startup.get('website', ''),
            'source': startup.get('source', '')
        }

        # Add any other fields that exist in your startup documents
        # This preserves all data from MongoDB
        for key, value in startup.items():
            if key not in startup_data and key != '_id' and key != 'entities':
                # Skip _id (already converted) and entities (handled separately)
                startup_data[key] = value

        startup_batch.append(startup_data)

    # LOAD: Insert into Neo4j
    print(f"\n[3] Creating {len(startup_batch)} Startup nodes in Neo4j...")

    query = """
    UNWIND $batch AS startup
    MERGE (s:Startup {startup_id: startup.startup_id})
    SET s.name = startup.name,
        s.description = startup.description,
        s.location = startup.location,
        s.funding_amount = startup.funding_amount,
        s.founded_date = startup.founded_date,
        s.website = startup.website,
        s.source = startup.source
    """

    neo4j.run_write_query(query, {'batch': startup_batch})

    logger.info(f"Created {len(startup_batch)} Startup nodes")
    return len(startup_batch)


def import_articles(mongo, neo4j):
    """
    Import Article nodes from MongoDB articles collection

    Includes all fields: title, description, url, published_date, source, etc.
    """

    print("\n" + "=" * 70)
    print("IMPORTING ARTICLES")
    print("=" * 70)

    # EXTRACT
    print("\n[1] Reading articles from MongoDB...")
    articles = list(mongo.db.articles.find())
    print(f"Found {len(articles)} articles")

    if len(articles) == 0:
        print("WARNING No articles found!")
        return 0

    # TRANSFORM
    print("\n[2] Transforming article data...")
    article_batch = []

    for article in articles:
        article_data = {
            'article_id': str(article['_id']),
            'title': article.get('title', ''),
            'description': article.get('description', ''),
            'url': article.get('url', ''),
            'published_date': article.get('published_date', ''),
            'source': article.get('source', '')
        }

        # Add any other fields
        for key, value in article.items():
            if key not in article_data and key != '_id' and key != 'entities':
                article_data[key] = value

        article_batch.append(article_data)

    # LOAD
    print(f"\n[3] Creating {len(article_batch)} Article nodes in Neo4j...")

    query = """
    UNWIND $batch AS article
    MERGE (a:Article {article_id: article.article_id})
    SET a.title = article.title,
        a.description = article.description,
        a.url = article.url,
        a.published_date = article.published_date,
        a.source = article.source
    """

    neo4j.run_write_query(query, {'batch': article_batch})

    logger.info(f"Created {len(article_batch)} Article nodes")
    return len(article_batch)


def import_github_repos(mongo, neo4j):
    """
    Import GitHubRepo nodes from MongoDB github_repos collection

    Includes: full_name, description, stars, forks, language, url, topics, etc.
    """

    print("\n" + "=" * 70)
    print("IMPORTING GITHUB REPOS")
    print("=" * 70)

    # EXTRACT
    print("\n[1] Reading repos from MongoDB...")
    repos = list(mongo.db.github_repos.find())
    print(f"Found {len(repos)} repos")

    if len(repos) == 0:
        print("WARNING No repos found!")
        return 0

    # TRANSFORM
    print("\n[2] Transforming repo data...")
    repo_batch = []

    for repo in repos:
        repo_data = {
            'repo_id': str(repo['_id']),
            'full_name': repo.get('full_name', ''),
            'description': repo.get('description', ''),
            'stars': repo.get('stars', 0),
            'forks': repo.get('forks', 0),
            'language': repo.get('language', ''),
            'url': repo.get('url', ''),
            'topics': str(repo.get('topics', []))  # Convert list to string
        }

        # Add any other fields
        for key, value in repo.items():
            if key not in repo_data and key != '_id' and key != 'entities':
                # Convert lists/dicts to strings for Neo4j
                if isinstance(value, (list, dict)):
                    repo_data[key] = str(value)
                else:
                    repo_data[key] = value

        repo_batch.append(repo_data)

    # LOAD
    print(f"\n[3] Creating {len(repo_batch)} GitHubRepo nodes in Neo4j...")

    query = """
    UNWIND $batch AS repo
    MERGE (r:GitHubRepo {repo_id: repo.repo_id})
    SET r.full_name = repo.full_name,
        r.description = repo.description,
        r.stars = repo.stars,
        r.forks = repo.forks,
        r.language = repo.language,
        r.url = repo.url,
        r.topics = repo.topics
    """

    neo4j.run_write_query(query, {'batch': repo_batch})

    logger.info(f"Created {len(repo_batch)} GitHubRepo nodes")
    return len(repo_batch)


def create_mention_relationships(mongo, neo4j):
    """
    Create MENTIONS relationships with mention counts and importance scores

    Enhanced version that tracks:
    - count: How many times entity mentioned in THIS document
    - importance: Calculated relevance score (0-1)
    - positions: Where in the text the entity appears

    This connects:
    - (Startup)-[:MENTIONS {count, importance}]->(Entity)
    - (Article)-[:MENTIONS {count, importance}]->(Entity)
    - (GitHubRepo)-[:MENTIONS {count, importance}]->(Entity)
    """

    print("\n" + "=" * 70)
    print("CREATING MENTION RELATIONSHIPS (WITH COUNTS)")
    print("=" * 70)

    total_relationships = 0

    # Process Startups
    print("\n[1] Creating Startup -> Entity relationships...")
    startups = list(mongo.db.startups.find({'entities': {'$exists': True}}))

    relationship_batch = []
    for startup in startups:
        startup_id = str(startup['_id'])
        entities = startup.get('entities', [])

        for entity in entities:
            # Get count from entity extractor (new format)
            count = entity.get('count', 1)
            
            # Calculate importance (entities mentioned more = more important)
            # Scale: 1 mention = 0.1, 5+ mentions = 1.0
            importance = min(count * 0.2, 1.0)
            
            relationship_batch.append({
                'doc_id': startup_id,
                'entity_text': entity.get('entity_text') or entity.get('text'),  # Support old & new format
                'entity_type': entity.get('entity_type') or entity.get('label'),
                'count': count,
                'importance': importance
            })

    if relationship_batch:
        query = """
        UNWIND $batch AS rel
        MATCH (s:Startup {startup_id: rel.doc_id})
        MATCH (e:Entity {entity_text: rel.entity_text, entity_type: rel.entity_type})
        MERGE (s)-[m:MENTIONS]->(e)
        SET m.count = rel.count,
            m.importance = rel.importance,
            m.created_at = datetime()
        """
        neo4j.run_write_query(query, {'batch': relationship_batch})
        total_mentions = sum(r['count'] for r in relationship_batch)
        print(f"  Created {len(relationship_batch)} relationships ({total_mentions} total mentions)")
        total_relationships += len(relationship_batch)

    # Process Articles
    print("\n[2] Creating Article -> Entity relationships...")
    articles = list(mongo.db.articles.find({'entities': {'$exists': True}}))

    relationship_batch = []
    for article in articles:
        article_id = str(article['_id'])
        entities = article.get('entities', [])

        for entity in entities:
            count = entity.get('count', 1)
            importance = min(count * 0.2, 1.0)
            
            relationship_batch.append({
                'doc_id': article_id,
                'entity_text': entity.get('entity_text') or entity.get('text'),
                'entity_type': entity.get('entity_type') or entity.get('label'),
                'count': count,
                'importance': importance
            })

    if relationship_batch:
        query = """
        UNWIND $batch AS rel
        MATCH (a:Article {article_id: rel.doc_id})
        MATCH (e:Entity {entity_text: rel.entity_text, entity_type: rel.entity_type})
        MERGE (a)-[m:MENTIONS]->(e)
        SET m.count = rel.count,
            m.importance = rel.importance,
            m.created_at = datetime()
        """
        neo4j.run_write_query(query, {'batch': relationship_batch})
        total_mentions = sum(r['count'] for r in relationship_batch)
        print(f"  Created {len(relationship_batch)} relationships ({total_mentions} total mentions)")
        total_relationships += len(relationship_batch)

    # Process GitHub Repos
    print("\n[3] Creating GitHubRepo -> Entity relationships...")
    repos = list(mongo.db.github_repos.find({'entities': {'$exists': True}}))

    relationship_batch = []
    for repo in repos:
        repo_id = str(repo['_id'])
        entities = repo.get('entities', [])

        for entity in entities:
            count = entity.get('count', 1)
            importance = min(count * 0.2, 1.0)
            
            relationship_batch.append({
                'doc_id': repo_id,
                'entity_text': entity.get('entity_text') or entity.get('text'),
                'entity_type': entity.get('entity_type') or entity.get('label'),
                'count': count,
                'importance': importance
            })

    if relationship_batch:
        query = """
        UNWIND $batch AS rel
        MATCH (r:GitHubRepo {repo_id: rel.doc_id})
        MATCH (e:Entity {entity_text: rel.entity_text, entity_type: rel.entity_type})
        MERGE (r)-[m:MENTIONS]->(e)
        SET m.count = rel.count,
            m.importance = rel.importance,
            m.created_at = datetime()
        """
        neo4j.run_write_query(query, {'batch': relationship_batch})
        total_mentions = sum(r['count'] for r in relationship_batch)
        print(f"  Created {len(relationship_batch)} relationships ({total_mentions} total mentions)")
        total_relationships += len(relationship_batch)

    # Update Entity nodes with global statistics
    print("\n[4] Updating Entity global statistics...")
    update_entity_statistics(neo4j)

    logger.info(f"Created {total_relationships} total relationships")
    return total_relationships


def update_entity_statistics(neo4j):
    """
    Update Entity nodes with global mention statistics
    
    Calculates:
    - total_mentions: Sum of all mention counts across all documents
    - document_count: Number of different documents mentioning this entity
    - avg_importance: Average importance score
    """
    query = """
    MATCH (e:Entity)
    OPTIONAL MATCH ()-[m:MENTIONS]->(e)
    WITH e, 
         sum(m.count) as total_mentions,
         count(DISTINCT m) as document_count,
         avg(m.importance) as avg_importance
    SET e.total_mentions = coalesce(total_mentions, 0),
        e.document_count = coalesce(document_count, 0),
        e.avg_importance = coalesce(avg_importance, 0.0),
        e.last_updated = datetime()
    RETURN count(e) as updated_entities
    """
    
    result = neo4j.run_query(query)
    count = result[0]['updated_entities'] if result else 0
    print(f"  Updated statistics for {count} entities")


def print_graph_statistics(neo4j):
    """
    Print statistics about the graph we just created
    """

    print("\n" + "=" * 70)
    print("GRAPH STATISTICS")
    print("=" * 70)

    # Count nodes by type
    print("\nNodes by type:")

    result = neo4j.run_query("MATCH (s:Startup) RETURN count(s) as count")
    print(f"  Startups: {result[0]['count']}")

    result = neo4j.run_query("MATCH (a:Article) RETURN count(a) as count")
    print(f"  Articles: {result[0]['count']}")

    result = neo4j.run_query("MATCH (r:GitHubRepo) RETURN count(r) as count")
    print(f"  GitHubRepos: {result[0]['count']}")

    result = neo4j.run_query("MATCH (e:Entity) RETURN count(e) as count")
    print(f"  Entities: {result[0]['count']}")

    # Count relationships
    print("\nRelationships:")
    result = neo4j.run_query("MATCH ()-[r:MENTIONS]->() RETURN count(r) as count")
    print(f"  MENTIONS: {result[0]['count']}")

    # Total
    total_nodes = neo4j.get_node_count()
    total_rels = neo4j.get_relationship_count()
    print(f"\nTotal nodes: {total_nodes}")
    print(f"Total relationships: {total_rels}")

    # Sample queries
    print("\n" + "=" * 70)
    print("SAMPLE QUERIES")
    print("=" * 70)

    print("\nTop 5 most mentioned entities:")
    result = neo4j.run_query("""
        MATCH (e:Entity)
        RETURN e.entity_text, e.entity_type, e.mention_count
        ORDER BY e.mention_count DESC
        LIMIT 5
    """)
    for i, record in enumerate(result, 1):
        print(f"  {i}. {record['e.entity_text']} ({record['e.entity_type']}): {record['e.mention_count']} mentions")

    print("\nSample startup with entities:")
    result = neo4j.run_query("""
        MATCH (s:Startup)-[:MENTIONS]->(e:Entity)
        RETURN s.name, collect(e.entity_text)[0..5] as entities
        LIMIT 1
    """)
    if result:
        print(f"  {result[0]['s.name']} mentions: {result[0]['entities']}")


def main():
    """Main ETL function"""

    print("=" * 70)
    print("MONGODB → NEO4J ETL")
    print("=" * 70)

    start_time = datetime.now()

    # Connect to databases
    print("\n[1] Connecting to databases...")
    mongo = MongoDBClient()
    neo4j = Neo4jClient()
    print("SUCCESS Connected to both databases\n")

    # Check current state
    print("[2] Checking current state...")
    node_count = neo4j.get_node_count()
    print(f"Neo4j currently has {node_count} nodes")

    if node_count > 0:
        print("\nWARNING: Neo4j already has data!")
        print("Options:")
        print("  1. Continue and merge with existing data (safe)")
        print("  2. Clear database and start fresh")
        response = input("\nContinue with merge? (y/n): ")

        if response.lower() != 'y':
            print("Aborted. Run neo4j.clear_database() if you want a fresh start.")
            mongo.close()
            neo4j.close()
            return

    # Import data
    print("\n" + "=" * 70)
    print("STARTING IMPORT")
    print("=" * 70)

    entity_count = import_entities(mongo, neo4j)
    startup_count = import_startups(mongo, neo4j)
    article_count = import_articles(mongo, neo4j)
    repo_count = import_github_repos(mongo, neo4j)
    relationship_count = create_mention_relationships(mongo, neo4j)

    # Print statistics
    print_graph_statistics(neo4j)

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print("\n" + "=" * 70)
    print("SUCCESS ETL COMPLETE")
    print("=" * 70)
    print(f"\nImported in {duration:.2f} seconds:")
    print(f"  ✅ {entity_count} entities")
    print(f"  ✅ {startup_count} startups")
    print(f"  ✅ {article_count} articles")
    print(f"  ✅ {repo_count} GitHub repos")
    print(f"  ✅ {relationship_count} MENTIONS relationships")

    print("\nNext steps:")
    print("  1. Open Neo4j Browser: http://localhost:7474")
    print("  2. Try this query: MATCH (s:Startup)-[:MENTIONS]->(e:Entity) RETURN s, e LIMIT 25")
    print("  3. Explore the graph visually!")
    print("  4. Ready for Sub-Phase 2.5 (Vector Embeddings)")

    # Cleanup
    mongo.close()
    neo4j.close()


if __name__ == "__main__":
    main()
