"""Code Review Pipeline — coder -> reviewer -> tester.

Demonstrates multi-agent pipeline pattern for code review.
"""
import asyncio
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


async def code_review_pipeline(task: str, code: str) -> dict:
    """Run code review pipeline: coder -> reviewer -> tester.
    
    Args:
        task: Description of what the code should do
        code: Source code to review
    
    Returns:
        Dict with final review, test results, and cost summary
    """
    from graxia_tool.agents import get_agent
    from graxia_tool.multi_agent import SharedState
    
    shared = SharedState()
    shared.put("task", task)
    shared.put("code", code)
    
    # Step 1: Coder reviews/analyzes the code
    coder = get_agent("coder")
    coder_result = await coder.run(
        f"Review this code for: {task}\n\nCode:\n{code}"
    )
    shared.put("coder_analysis", coder_result.output)
    
    # Step 2: Reviewer checks for style, security, performance
    reviewer = get_agent("reviewer")
    reviewer_result = await reviewer.run(
        f"Check code for style, security, performance issues.\n\nCode:\n{code}\n\nCoder notes:\n{coder_result.output}"
    )
    shared.put("reviewer_notes", reviewer_result.output)
    
    # Step 3: Tester suggests test cases
    tester = get_agent("tester")
    tester_result = await tester.run(
        f"Generate test cases for this code.\n\nCode:\n{code}\n\nReview notes:\n{reviewer_result.output}"
    )
    shared.put("test_cases", tester_result.output)
    
    return {
        "task": task,
        "coder_analysis": str(coder_result.output),
        "reviewer_notes": str(reviewer_result.output),
        "test_cases": str(tester_result.output),
        "total_cost_usd": sum([
            coder_result.cost_usd,
            reviewer_result.cost_usd,
            tester_result.cost_usd,
        ]),
        "total_tokens": sum([
            coder_result.tokens_used,
            reviewer_result.tokens_used,
            tester_result.tokens_used,
        ]),
    }


async def main():
    print("=" * 60)
    print("CODE REVIEW PIPELINE EXAMPLE")
    print("=" * 60)
    
    sample_code = '''
def calculate_total(items, tax_rate):
    total = 0
    for item in items:
        total += item["price"] * item["quantity"]
    tax = total * tax_rate
    return total + tax
'''
    
    print(f"\nReviewing code:\n{sample_code}")
    
    result = await code_review_pipeline(
        task="Calculate shopping cart total with tax",
        code=sample_code,
    )
    
    print("\n--- CODER ANALYSIS ---")
    print(result["coder_analysis"][:500])
    print("\n--- REVIEWER NOTES ---")
    print(result["reviewer_notes"][:500])
    print("\n--- TEST CASES ---")
    print(result["test_cases"][:500])
    
    print(f"\n--- COST SUMMARY ---")
    print(f"Total tokens: {result['total_tokens']}")
    print(f"Total cost: ${result['total_cost_usd']:.6f}")
    print(f"Cost per agent: ${result['total_cost_usd']/3:.6f}")


if __name__ == "__main__":
    asyncio.run(main())
