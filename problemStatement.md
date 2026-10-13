# AI-Powered Restaurant Recommendation System

## Context

ZomatoReco is a restaurant recommendation service inspired by Zomato. It suggests restaurants from a real-world dataset by combining structured filters with a large language model, so results are both relevant and explained in plain language.

The product is a single flow: collect what the user wants, narrow the restaurant catalog to matching options, ask an LLM to rank and explain those options, then show a short list the user can act on.

## Objective

Build an application that:

- Takes user preferences such as location, budget, cuisine, and ratings
- Uses a real-world restaurant dataset
- Uses an LLM to produce personalized, human-like recommendations
- Displays clear, useful results

## System workflow

### 1. Data ingestion

Load and preprocess the Zomato restaurant dataset from Hugging Face:

[ManikaSaini/zomato-restaurant-recommendation](https://huggingface.co/datasets/ManikaSaini/zomato-restaurant-recommendation)

Extract the fields needed for filtering and display, including restaurant name, location, cuisine, cost, and rating.

### 2. User input

Collect preferences before any recommendation is generated:

| Preference | Examples |
| --- | --- |
| Location | Delhi, Bangalore |
| Budget | Low, medium, high |
| Cuisine | Italian, Chinese |
| Minimum rating | Numeric threshold |
| Additional preferences | Family-friendly, quick service |

### 3. Integration layer

Filter and prepare restaurant records that match the user's input. Pass that structured subset into an LLM prompt designed so the model can reason over the options and rank them.

### 4. Recommendation engine

The LLM is responsible for:

- Ranking the filtered restaurants
- Explaining why each recommendation fits the user's preferences
- Optionally summarizing the set of choices

### 5. Output display

Show the top recommendations in a readable format. Each result includes:

- Restaurant name
- Cuisine
- Rating
- Estimated cost
- AI-generated explanation

## Success criteria

A working system loads the dataset, accepts the preferences above, returns a ranked shortlist grounded in that data, and explains each suggestion in language a diner can understand.
