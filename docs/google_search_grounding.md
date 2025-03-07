# Google Search Grounding Implementation

This document explains how our bot implements Google Search grounding through the Gemini API and how we comply with Google's guidelines.

## Overview

Our chatbot uses Google's Gemini API with search grounding enabled, allowing it to provide more accurate and up-to-date information by searching the web. When the model determines that a search is necessary to answer a question, it will automatically use Google Search and include relevant information in its response.

## Implementation Details

### Configuration

Search grounding is configured in the `GeminiAPI` class under `src/services/api/gemini.py`. We set up the Google Search tool during initialization:

```python
# Set up Google Search tool for search grounding
self._google_search_tool = Tool(
    google_search = GoogleSearch()
)

# Add the tool to the generation config
self._generation_config = GenerateContentConfig(
    temperature=0.6,
    top_p=1,
    top_k=40,
    max_output_tokens=self.MAX_TOTAL_TOKENS - self.MAX_PROMPT_TOKENS,
    tools=[self._google_search_tool]  # Add the Google Search tool
)
```

### Handling Search-Grounded Responses

When we receive a response from Gemini, we:

1. Detect whether search grounding was used through multiple methods:
   - Checking for `grounding_metadata` in the response
   - Looking for search function calls
   - Examining the response for citation patterns

2. For search-grounded responses:
   - We apply minimal formatting to preserve the original content
   - We extract and display search suggestions from the response metadata
   - We do not modify the content or intersperse other content with the grounded results

3. For regular (non-search-grounded) responses:
   - We apply our standard formatting and enhancements

## Compliance with Google's Guidelines

We follow Google's guidelines for using Grounding with Google Search:

1. **Display Requirements**:
   - We display both the Grounded Results and Search Suggestions to the end user
   - We do not modify or intersperse content with the Grounded Results or Search Suggestions
   - We display Search Suggestions along with the response when provided

2. **Storage Policy**:
   - We do not store Search Suggestions or Links
   - We keep chat session context in memory only for 30 minutes
   - We do not persist chat history to disk or database

3. **Tracking Limitations**:
   - We do not track whether user interactions were specifically with Search Suggestions or Links
   - We only track general usage statistics for service health monitoring

## User Experience

When a user asks a question that requires search grounding:

1. The user sees a response with relevant information from the web
2. Citations may be included in the response when relevant
3. At the bottom of the response, "Related searches:" shows suggested search queries

Note that not all responses will use search grounding. The model automatically determines when web search is needed to provide an accurate answer.

## Limitations

- Search grounding is only available when the API service is online
- Usage is subject to API rate limits and quotas
- Search grounding may not be used for every query, only when the model determines it's necessary 