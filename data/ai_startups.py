"""
Real AI Startup URLs for Scraping
10 well-known AI companies with accessible About pages
"""

AI_STARTUPS = [
    {
        'name': 'OpenAI',
        'url': 'https://openai.com/about/',
        'category': 'AI Research',
        'founded': '2015'
    },
    {
        'name': 'Anthropic',
        'url': 'https://www.anthropic.com/company',
        'category': 'AI Safety',
        'founded': '2021'
    },
    {
        'name': 'Hugging Face',
        'url': 'https://huggingface.co/huggingface',
        'category': 'ML Platform',
        'founded': '2016'
    },
    {
        'name': 'Cohere',
        'url': 'https://cohere.com/about',
        'category': 'Enterprise AI',
        'founded': '2019'
    },
    {
        'name': 'Stability AI',
        'url': 'https://stability.ai/about',
        'category': 'Generative AI',
        'founded': '2020'
    },
    {
        'name': 'Replicate',
        'url': 'https://replicate.com/about',
        'category': 'ML Infrastructure',
        'founded': '2019'
    },
    {
        'name': 'Adept',
        'url': 'https://www.adept.ai/about',
        'category': 'AI Agents',
        'founded': '2022'
    },
    {
        'name': 'Character.AI',
        'url': 'https://character.ai/',
        'category': 'Conversational AI',
        'founded': '2021'
    },
    {
        'name': 'Midjourney',
        'url': 'https://www.midjourney.com/about',
        'category': 'AI Art',
        'founded': '2021'
    },
    {
        'name': 'Runway',
        'url': 'https://runwayml.com/about/',
        'category': 'Video AI',
        'founded': '2018'
    }
]


def get_startup_urls():
    """Get list of URLs to scrape"""
    return [startup['url'] for startup in AI_STARTUPS]


def get_startup_info(name):
    """Get startup info by name"""
    for startup in AI_STARTUPS:
        if startup['name'].lower() == name.lower():
            return startup
    return None


if __name__ == "__main__":
    print("AI Startups to Scrape:")
    print("=" * 50)
    for i, startup in enumerate(AI_STARTUPS, 1):
        print(f"{i}. {startup['name']} ({startup['founded']})")
        print(f"   Category: {startup['category']}")
        print(f"   URL: {startup['url']}\n")