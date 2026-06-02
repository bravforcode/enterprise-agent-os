"""Data Analysis Pipeline — researcher -> data_engineer -> documenter.

Demonstrates multi-agent pattern for data analysis and reporting.
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


async def data_analysis_pipeline(question: str, data_source: str) -> dict:
    """Run data analysis pipeline: researcher -> data_engineer -> documenter.
    
    Args:
        question: The business question to answer
        data_source: Description of available data
    
    Returns:
        Dict with analysis, results, and final report
    """
    from graxia_tool.agents import get_agent
    
    # Step 1: Research — understand the question and approach
    researcher = get_agent("researcher")
    research_result = await researcher.run(
        f"Research methodology to answer: {question}\n\nData source: {data_source}"
    )
    
    # Step 2: Data engineering — design queries/transformation
    data_eng = get_agent("data_engineer")
    data_result = await data_eng.run(
        f"Design data pipeline for: {question}\n\nData source: {data_source}\n\nResearch notes:\n{research_result.output}"
    )
    
    # Step 3: Documentation — write final report
    documenter = get_agent("documenter")
    doc_result = await documenter.run(
        f"Write executive summary report.\n\nResearch:\n{research_result.output}\n\nData analysis:\n{data_result.output}"
    )
    
    return {
        "question": question,
        "research_approach": str(research_result.output),
        "data_pipeline": str(data_result.output),
        "executive_summary": str(doc_result.output),
        "total_cost_usd": sum([
            research_result.cost_usd,
            data_result.cost_usd,
            doc_result.cost_usd,
        ]),
    }


async def main():
    print("=" * 60)
    print("DATA ANALYSIS PIPELINE EXAMPLE")
    print("=" * 60)
    
    result = await data_analysis_pipeline(
        question="What is the customer churn rate trend over the last 6 months?",
        data_source="PostgreSQL: customers table (10K rows), subscriptions table (50K rows), events table (1M rows)",
    )
    
    print(f"\nQuestion: {result['question']}")
    print(f"\n--- RESEARCH APPROACH ---")
    print(result["research_approach"][:500])
    print(f"\n--- DATA PIPELINE ---")
    print(result["data_pipeline"][:500])
    print(f"\n--- EXECUTIVE SUMMARY ---")
    print(result["executive_summary"][:500])
    
    print(f"\n--- COST ---")
    print(f"Total: ${result['total_cost_usd']:.6f}")


if __name__ == "__main__":
    asyncio.run(main())
