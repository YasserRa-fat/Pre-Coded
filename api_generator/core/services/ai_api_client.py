import os
import logging
import aiohttp
import asyncio
import json
import re
import traceback

logger = logging.getLogger(__name__)

TOGETHER_API_KEY = os.getenv("TOGETHER_AI_API_KEY")
MISTRAL_MODEL = "mistralai/Mixtral-8x7B-Instruct-v0.1"
API_URL = "https://api.together.xyz/inference"

async def make_ai_api_call(prompt: str, max_tokens: int = 2048, temperature: float = 0.2) -> str:
    """Make an async API call to the AI service with retry on rate limiting"""
    max_retries = 3
    base_retry_delay = 2  # start with 2 second delay
    
    # Safety check - ensure prompt is a string
    if not isinstance(prompt, str):
        raise ValueError(f"Prompt must be a string, got {type(prompt)}")
    
    # Pre-process prompt to handle Django template tags that could cause issues
    try:
        # Replace Django template tags with placeholders before sending to API
        prompt = prompt.replace("{% csrf_token %}", "CSRF_TOKEN_PLACEHOLDER")
        prompt = prompt.replace("{%", "DJANGO_TAG_START")
        prompt = prompt.replace("%}", "DJANGO_TAG_END")
    except Exception as e:
        logger.error(f"Error preprocessing prompt: {str(e)}")
        raise
    
    last_error = None
    for attempt in range(max_retries):
        try:
            logger.info(f"Making API call attempt {attempt + 1}/{max_retries}")
            
            # Wait before each attempt to avoid rate limits
            retry_delay = base_retry_delay * (attempt + 1)
            await asyncio.sleep(retry_delay)
            
            headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
            payload = {
                "model": MISTRAL_MODEL,
                "prompt": prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": 0.7,
                "frequency_penalty": 0.5
            }
            
            timeout = aiohttp.ClientTimeout(total=60)  # 60 second timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(API_URL, json=payload, headers=headers) as response:
                    if response.status == 429:  # Rate limited
                        logger.warning(f"Rate limited by AI API (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            raise Exception("Max retries exceeded due to rate limiting")
                    
                    # Handle all non-2xx responses
                    if response.status >= 400:
                        error_text = await response.text()
                        logger.error(f"API error {response.status}: {error_text}")
                        last_error = f"API returned status code {response.status}: {error_text}"
                        if attempt < max_retries - 1:
                            continue
                        raise Exception(last_error)
                            
                    result = await response.json()
                    
                    if not result.get("choices"):
                        last_error = "Invalid response format from AI API"
                        if attempt < max_retries - 1:
                            continue
                        raise Exception(last_error)
                    
                    # Post-process the result to restore Django template tags
                    response_text = result["choices"][0]["text"]
                    response_text = response_text.replace("CSRF_TOKEN_PLACEHOLDER", "{% csrf_token %}")
                    response_text = response_text.replace("DJANGO_TAG_START", "{%")
                    response_text = response_text.replace("DJANGO_TAG_END", "%}")
                    
                    return response_text
                    
        except asyncio.TimeoutError:
            last_error = f"API call timed out (attempt {attempt + 1}/{max_retries})"
            logger.error(last_error)
            if attempt == max_retries - 1:
                raise Exception(last_error)
        except aiohttp.ClientError as e:
            last_error = f"API request failed: {str(e)}"
            logger.error(last_error)
            if attempt == max_retries - 1:
                raise Exception(last_error)
        except Exception as e:
            last_error = f"Error calling AI API: {str(e)}"
            logger.error(last_error)
            logger.error(traceback.format_exc())
            if attempt == max_retries - 1:
                raise
            
        # Wait before next retry
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
    
    raise Exception(last_error or "Failed to get response from AI API after all retries") 