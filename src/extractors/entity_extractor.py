"""Entity Extractor using spaCy NER (Named Entity Recognition)"""

import spacy
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class EntityExtractor:
    """Extracts named entities from text using spaCy's transformer model"""

    def __init__(self, model_name: str = "en_core_web_trf"):
        """Initialize the entity extractor"""
        logger.info(f"Loading spaCy model: {model_name}...")

        try:
            self.nlp = spacy.load(model_name)

            logger.info("spaCy model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load spaCy model: {e}")
            raise

    def extract_entities(self, text: str) -> List[Dict]:
        """Extract entities with mention counts"""
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
        """Extract entities grouped by type"""

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
        """Extract just company/organization names"""

        entities_by_type = self.extract_entities_by_type(text, entity_types=['ORG'])
        return entities_by_type.get('ORG', [])

    def get_people_names(self, text: str) -> List[str]:
        """Extract just people names"""

        entities_by_type = self.extract_entities_by_type(text, entity_types=['PERSON'])
        return entities_by_type.get('PERSON', [])

    def get_locations(self, text: str) -> List[str]:
        """Extract just locations (cities, countries, states)"""

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
    print("ALL TESTS COMPLETE")
    print("=" * 70)
