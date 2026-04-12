from __future__ import annotations

import uuid

from langgraph.types import Command
from rich.prompt import Confirm, Prompt

from src.config import load_config
from src.graph import compile_graph
from src.utils.container import DockerSandbox
from src.utils.output import (
    console,
    print_agent_status,
    print_checkpoint,
    print_file_list,
    print_header,
    print_markdown,
    print_review_comments,
    print_test_results,
)
from src.utils.workspace import prepare_workspace


def handle_interrupt(interrupt_value: dict) -> dict:
    """Handle a human-in-the-loop interrupt and return the resume value."""
    interrupt_type = interrupt_value.get("type", "unknown")

    if interrupt_type == "architecture_review":
        print_header("Architecture Review")
        print_markdown(interrupt_value.get("architecture_doc", ""))
        console.print(f"\n[bold]Tech Stack:[/bold] {interrupt_value.get('tech_stack', {})}")
        console.print(f"[bold]Files planned:[/bold] {len(interrupt_value.get('folder_structure', []))}")
        for f in interrupt_value.get("folder_structure", []):
            console.print(f"  [dim]{f}[/dim]")

        print_checkpoint("Do you approve this architecture?")
        approved = Confirm.ask("Approve")
        feedback = ""
        if not approved:
            feedback = Prompt.ask("Feedback", default="Please revise")
        return {"approved": approved, "feedback": feedback}

    elif interrupt_type == "final_review":
        print_header("Final Review")
        files = interrupt_value.get("generated_files", [])
        console.print(f"[bold]Generated files:[/bold] {len(files)}")
        for f in files:
            console.print(f"  [cyan]{f}[/cyan]")

        console.print()
        print_test_results(interrupt_value.get("test_results", []))
        passing = interrupt_value.get("tests_passing", False)
        console.print(f"\n[bold]Tests passing:[/bold] {'[green]Yes[/green]' if passing else '[red]No[/red]'}")

        print_checkpoint("Do you approve the final output?")
        approved = Confirm.ask("Approve")
        return {"approved": approved}

    else:
        console.print(f"[yellow]Unknown interrupt type: {interrupt_type}[/yellow]")
        approved = Confirm.ask("Continue")
        return {"approved": approved}


def main():
    config = load_config()
    workspace_path = prepare_workspace(config.output_dir)
    thread_id = str(uuid.uuid4())
    run_config = {"configurable": {"thread_id": thread_id}}

    # Check for Docker and start sandbox if available
    sandbox = None
    use_sandbox = config.use_sandbox

    if use_sandbox:
        if DockerSandbox.is_docker_available():
            console.print("[bold]Docker detected[/bold] — starting sandbox container...")
            sandbox = DockerSandbox(workspace_path)
            try:
                sandbox.start()
                console.print(f"[green]Sandbox running:[/green] {sandbox.container_name}")
            except Exception as e:
                console.print(f"[yellow]Failed to start sandbox: {e}[/yellow]")
                console.print("[dim]Falling back to direct execution on host.[/dim]")
                sandbox = None
        else:
            console.print("[yellow]Docker not available.[/yellow] Running shell commands directly on host.")
            console.print("[dim]Install Docker for isolated execution: https://docs.docker.com/get-docker/[/dim]\n")

    graph = compile_graph(config, sandbox=sandbox)

    # Get user requirements
    print_header("Multi-Agent Dev Team")
    console.print("Describe the web application you want to build.\n")
    requirements = Prompt.ask("[bold green]Requirements")

    if not requirements.strip():
        console.print("[red]No requirements provided. Exiting.[/red]")
        _cleanup(sandbox)
        return

    # Initial state
    initial_state = {
        "user_requirements": requirements,
        "messages": [],
        "workspace_path": workspace_path,
        "review_iteration": 0,
        "architecture_approved": False,
        "final_approved": False,
        "review_approved": False,
        "generated_files": [],
        "review_comments": [],
        "test_files": [],
        "test_results": [],
        "tests_passing": False,
        "user_stories": [],
        "task_plan": [],
        "architecture_doc": "",
        "folder_structure": [],
        "tech_stack": {},
        "current_agent": "",
        "error": "",
        "_max_review_iterations": config.max_review_iterations,
    }

    mode = "sandbox" if sandbox else "host"
    print_header("Starting Pipeline")
    console.print(f"[dim]Execution mode: {mode}[/dim]")
    console.print("[dim]PM → Architect → Human Review → Developer → Reviewer → Tester → Human Review[/dim]\n")

    try:
        # Run the graph
        result = graph.invoke(initial_state, config=run_config)

        # Handle interrupts in a loop
        while True:
            snapshot = graph.get_state(run_config)
            if not snapshot.next:
                break

            if hasattr(snapshot, "tasks") and snapshot.tasks:
                for task in snapshot.tasks:
                    if hasattr(task, "interrupts") and task.interrupts:
                        for intr in task.interrupts:
                            resume_value = handle_interrupt(intr.value)
                            result = graph.invoke(
                                Command(resume=resume_value),
                                config=run_config,
                            )
            else:
                break

        # Final output
        print_header("Project Complete")
        console.print(f"[bold]Output directory:[/bold] {workspace_path}")

        generated = result.get("generated_files", []) if isinstance(result, dict) else []
        if generated:
            print_file_list(generated)
        else:
            console.print("[dim]No files generated.[/dim]")

        if result.get("error") if isinstance(result, dict) else None:
            console.print(f"\n[red]Error:[/red] {result['error']}")

        console.print("\n[green]Done![/green]")

    finally:
        _cleanup(sandbox)


def _cleanup(sandbox: DockerSandbox | None) -> None:
    """Stop and remove the sandbox container if running."""
    if sandbox is not None:
        console.print("[dim]Stopping sandbox container...[/dim]")
        sandbox.stop()
        console.print("[dim]Sandbox removed.[/dim]")


if __name__ == "__main__":
    main()
