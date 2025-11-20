"""
Entity Extractor using spaCy NER (Named Entity Recognition)

This module extracts structured entities from unstructured text.

What it does:
- Takes text like: "OpenAI, founded in San Francisco, raised $13B from Microsoft"
- Extracts entities like:
  * OpenAI → ORGANIZATION
  * San Francisco → LOCATION (GPE = Geo-Political Entity)
  * $13B → MONEY
  * Microsoft → ORGANIZATION

Why we need this:
- To build the Neo4j knowledge graph, we need to know what's a company, person, location, etc.
- spaCy automatically identifies these using AI (transformer model)
"""

import spacy
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class EntityExtractor:
    """
    Extracts named entities from text using spaCy's transformer model

    Example usage:
        extractor = EntityExtractor()
        text = "OpenAI raised $13B from Microsoft"
        entities = extractor.extract_entities(text)
        # Returns: [
        #   {'text': 'OpenAI', 'label': 'ORG', 'start': 0, 'end': 6},
        #   {'text': '$13B', 'label': 'MONEY', 'start': 14, 'end': 18},
        #   {'text': 'Microsoft', 'label': 'ORG', 'start': 24, 'end': 33}
        # ]
    """

    def __init__(self, model_name: str = "en_core_web_trf"):
        """
        Initialize the entity extractor

        Args:
            model_name: spaCy model to use (default: en_core_web_trf = transformer model)

        What happens here:
            1. Loads the spaCy model into memory (this is the "brain")
            2. Model stays loaded for fast repeated use
            3. If model fails to load, raises an error
        """
        logger.info(f"Loading spaCy model: {model_name}...")

        try:
            self.nlp = spacy.load(model_name)

            logger.info("✅ spaCy model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load spaCy model: {e}")
            raise

    def extract_entities(self, text: str) -> List[Dict]:
        """
        Extract entities with mention counts
        
        Returns:
            List of dicts with:
            - entity_text: The entity text
            - entity_type: ORG, PERSON, GPE, etc.
            - count: How many times mentioned
            - positions: List of (start, end) positions
            - confidence: spaCy confidence score
        """
        doc = self.nlp(text)
        
        # Count mentions using a dictionary
        entity_counts = {}
        
        for ent in doc.ents:
            # Filter out unwanted types
            if ent.label_ in ['CARDINAL', 'ORDINAL', 'QUANTITY', 'DATE', 'TIME']:
                continue
                
            # Normalize the entity text
            entity_text = ent.text.strip()
            entity_type = ent.label_
            
            # Create unique key
            key = (entity_text, entity_type)
            
            if key not in entity_counts:
                entity_counts[key] = {
                    'entity_text': entity_text,
                    'entity_type': entity_type,
                    'count': 0,
                    'positions': []
                }
            
            # Increment count and track position
            entity_counts[key]['count'] += 1
            entity_counts[key]['positions'].append((ent.start_char, ent.end_char))
        
        # Convert to list
        entities = list(entity_counts.values())
        
        logger.info(f"Extracted {len(entities)} unique entities with {sum(e['count'] for e in entities)} total mentions")
        
        return entities

    def extract_entities_by_type(
        self,
        text: str,
        entity_types: Optional[List[str]] = None
    ) -> Dict[str, List[str]]:
        """
        Extract entities grouped by type

        Args:
            text: Text to extract from
            entity_types: List of entity types to extract (e.g., ['ORG', 'PERSON', 'GPE'])
                         If None, extracts all types

        Returns:
            Dictionary with entity types as keys, lists of entity texts as values
            Example:
            {
                'ORG': ['OpenAI', 'Microsoft', 'Y Combinator'],
                'PERSON': ['Sam Altman', 'Elon Musk'],
                'GPE': ['San Francisco', 'New York'],
                'MONEY': ['$13 billion', '$500M']
            }

        Why this is useful:
            - When building the graph, we want to group companies, people, locations separately
            - Makes it easier to create different node types in Neo4j
        """

        # Get all entities first
        all_entities = self.extract_entities(text)

        # Group by type
        grouped = {}

        for ent in all_entities:
            label = ent['label']
            text = ent['text']

            # If entity_types specified, only include those types
            if entity_types and label not in entity_types:
                continue

            # Add to grouped dictionary
            if label not in grouped:
                grouped[label] = []

            grouped[label].append(text)

        return grouped

    def get_company_names(self, text: str) -> List[str]:
        """
        Extract just company/organization names

        Args:
            text: Text to extract from

        Returns:
            List of company names (ORG entities)

        Why a separate method:
            - Companies are the most important entities for your project
            - Convenience method so you don't have to filter ORG entities manually
        """

        entities_by_type = self.extract_entities_by_type(text, entity_types=['ORG'])
        return entities_by_type.get('ORG', [])

    def get_people_names(self, text: str) -> List[str]:
        """
        Extract just people names

        Args:
            text: Text to extract from

        Returns:
            List of person names (PERSON entities)
        """

        entities_by_type = self.extract_entities_by_type(text, entity_types=['PERSON'])
        return entities_by_type.get('PERSON', [])

    def get_locations(self, text: str) -> List[str]:
        """
        Extract just locations (cities, countries, states)

        Args:
            text: Text to extract from

        Returns:
            List of locations (GPE entities)

        Note: GPE = Geo-Political Entity (countries, cities, states)
        """

        entities_by_type = self.extract_entities_by_type(text, entity_types=['GPE'])
        return entities_by_type.get('GPE', [])


# =============================================================================
# BELOW IS EXAMPLE CODE - NOT PART OF THE CLASS
# This shows you how to use the EntityExtractor
# =============================================================================

if __name__ == "__main__":
    """
    Test the EntityExtractor with sample text

    Run this file directly to test:
        python src/extractors/entity_extractor.py
    """

    # Set up logging so we can see what's happening
    logging.basicConfig(level=logging.INFO)

    # Sample text to test
    sample_text = """
    Anthropic, founded in San Francisco by Dario Amodei and Daniela Amodei,
    raised $500 million in Series C funding from Google and Spark Capital.
    The company develops AI safety technology and is based in California.
    """

    print("=" * 70)
    print("TESTING ENTITY EXTRACTOR")
    print("=" * 70)
    print(f"\nInput text:\n{sample_text}\n")

    # Create extractor
    print("Creating EntityExtractor...")
    extractor = EntityExtractor()

    # Test 1: Extract all entities
    print("\n" + "=" * 70)
    print("TEST 1: Extract all entities")
    print("=" * 70)
    all_entities = extractor.extract_entities(sample_text)

    for i, ent in enumerate(all_entities, 1):
        print(f"{i}. {ent['text']:20s} → {ent['label']}")

    # Test 2: Extract entities grouped by type
    print("\n" + "=" * 70)
    print("TEST 2: Extract entities grouped by type")
    print("=" * 70)
    grouped = extractor.extract_entities_by_type(sample_text)

    for entity_type, entities in grouped.items():
        print(f"\n{entity_type}:")
        for ent in entities:
            print(f"  - {ent}")

    # Test 3: Extract just companies
    print("\n" + "=" * 70)
    print("TEST 3: Extract just companies")
    print("=" * 70)
    companies = extractor.get_company_names(sample_text)
    print(f"Companies: {companies}")

    # Test 4: Extract just people
    print("\n" + "=" * 70)
    print("TEST 4: Extract just people")
    print("=" * 70)
    people = extractor.get_people_names(sample_text)
    print(f"People: {people}")

    # Test 5: Extract just locations
    print("\n" + "=" * 70)
    print("TEST 5: Extract just locations")
    print("=" * 70)
    locations = extractor.get_locations(sample_text)
    print(f"Locations: {locations}")

    print("\n" + "=" * 70)
    print("✅ ALL TESTS COMPLETE")
    print("=" * 70)
