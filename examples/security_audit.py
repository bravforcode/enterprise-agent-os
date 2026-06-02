"""Security Audit Pipeline — auditor -> security_auditor -> reviewer.

Demonstrates security review pipeline with 3 specialized agents.
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


async def security_audit_pipeline(target: str, scope: str) -> dict:
    """Run security audit pipeline.
    
    Args:
        target: What to audit (e.g., "API endpoint", "auth system", "data pipeline")
        scope: Boundaries of the audit
    
    Returns:
        Dict with findings, risk assessment, and recommendations
    """
    from graxia_tool.agents import get_agent
    
    # Step 1: Auditor — general compliance/best practices
    auditor = get_agent("auditor")
    audit_result = await auditor.run(
        f"Audit for compliance and best practices: {target}\n\nScope: {scope}"
    )
    
    # Step 2: Security auditor — deep security analysis
    sec_auditor = get_agent("security_auditor")
    sec_result = await sec_auditor.run(
        f"Security analysis: {target}\n\nScope: {scope}\n\nCompliance notes:\n{audit_result.output}"
    )
    
    # Step 3: Reviewer — final review and prioritization
    reviewer = get_agent("reviewer")
    review_result = await reviewer.run(
        f"Review findings, prioritize by severity, suggest fixes.\n\nAudit findings:\n{audit_result.output}\n\nSecurity analysis:\n{sec_result.output}"
    )
    
    return {
        "target": target,
        "compliance_findings": str(audit_result.output),
        "security_findings": str(sec_result.output),
        "prioritized_recommendations": str(review_result.output),
        "total_cost_usd": sum([
            audit_result.cost_usd,
            sec_result.cost_usd,
            review_result.cost_usd,
        ]),
    }


async def main():
    print("=" * 60)
    print("SECURITY AUDIT PIPELINE EXAMPLE")
    print("=" * 60)
    
    result = await security_audit_pipeline(
        target="User authentication API",
        scope="JWT-based auth, login, logout, password reset, 2FA",
    )
    
    print(f"\nTarget: {result['target']}")
    print(f"\n--- COMPLIANCE FINDINGS ---")
    print(result["compliance_findings"][:500])
    print(f"\n--- SECURITY FINDINGS ---")
    print(result["security_findings"][:500])
    print(f"\n--- RECOMMENDATIONS ---")
    print(result["prioritized_recommendations"][:500])
    
    print(f"\n--- COST ---")
    print(f"Total: ${result['total_cost_usd']:.6f}")


if __name__ == "__main__":
    asyncio.run(main())
