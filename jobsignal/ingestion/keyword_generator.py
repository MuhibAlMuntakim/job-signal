import json
from loguru import logger
from groq import Groq
from jobsignal.config.settings import get_settings
from jobsignal.config.rate_limiter import rate_limiter
from jobsignal.database.models import CandidateProfile

def generate_search_keywords(profile: CandidateProfile) -> list[str]:
    """
    Generate search keywords based on the candidate's profile.
    
    Combines rule-based mapping with Groq-generated keywords.
    
    Args:
        profile: The CandidateProfile object.
        
    Returns:
        A list of search query strings.
    """
    settings = get_settings()
    
    settings = get_settings()
    
    # LLM-based high-quality keyword generation
    # Source B: Groq generated
    client = Groq(api_key=settings.groq_api_key)
    rate_limiter.wait_if_needed()
    
    system_prompt = "You are a job search assistant. Your goal is to generate the 10 most effective, high-quality job search keywords based on a resume."
    remote_context = " (Remote, global - work from anywhere)" if profile.preferred_remote.lower() == "remote" else ""
    user_prompt = f"""Identify the 10 best-quality job search keywords (job titles or specific technical roles) for this candidate for {profile.preferred_remote}{remote_context} positions.
Focus on highly relevant, high-performing keywords that will yield the best matches.

Return JSON: 
{{
  "keywords": [array of 10 strings]
}}

Profile Summary:
Skills: {profile.extracted_skills}
Experience Level: {profile.experience_level}
Sectors of Experience: {profile.sectors_of_experience}"""

    try:
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,  # As per tech decisions: 0.1 for all calls
            response_format={"type": "json_object"}
        )
        llm_result = json.loads(response.choices[0].message.content)
        llm_keywords = llm_result.get("keywords", [])[:10]
    except Exception as e:
        logger.error(f"Groq keyword generation failed: {e}")
        llm_keywords = []

    # Filter and clean
    seen = set()
    deduped = []
    for k in llm_keywords:
        k_clean = k.strip()
        if k_clean.lower() not in seen and k_clean:
            deduped.append(k_clean)
            seen.add(k_clean.lower())
            
    # If LLM failed, fallback to rule-based just to ensure we have something
    if not deduped:
        rule_keywords = ["AI Engineer", "ML Engineer", "Data Scientist", "Python Developer"]
        deduped = rule_keywords[:10]

    logger.info(f"Generated {len(deduped)} high-quality keywords: {deduped}")
    return deduped[:10]
