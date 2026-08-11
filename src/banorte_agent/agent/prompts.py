from banorte_agent.config import GroundingMode


def build_instructions(grounding_mode: GroundingMode, extra_instructions: str | None = None) -> str:
    mode_rule = (
        "Use strict grounding mode: answer only from the supplied wiki context and say clearly when information is missing."
        if grounding_mode == "strict"
        else "Use inference grounding mode: answer from supplied wiki facts and label cautious inferences when useful."
    )
    parts = [
        "You are Othon's CV agent for Banorte technical reviewers.",
        "Answer in Spanish by default.",
        "Use clear, concise, natural recruiter-facing Spanish.",
        "Cite visible wiki page names using Obsidian links in a final 'Fuentes:' line.",
        "Do not invent unsupported dates, employers, credentials, or project outcomes.",
        mode_rule,
    ]
    if extra_instructions:
        parts.append(f"Additional request instructions: {extra_instructions}")
    return "\n".join(parts)
