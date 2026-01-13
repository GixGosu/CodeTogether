//! /task command - Submit a task to Claude.

use serenity::all::{
    CommandInteraction, CommandOptionType, Context, CreateCommand, CreateCommandOption,
    CreateInteractionResponse, CreateInteractionResponseMessage, EditInteractionResponse,
};
use tracing::{error, info};

use crate::client::{ExecutionMode, TaskRequest, TaskStatus, WrapperClient};

/// Create the command registration.
pub fn register() -> CreateCommand {
    CreateCommand::new("task")
        .description("Submit a task to Claude Code")
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::String,
                "prompt",
                "The task/prompt to send to Claude",
            )
            .required(true),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::String,
                "project",
                "Project name to work on (use /project list to see available)",
            )
            .required(false),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::User,
                "target",
                "Use another user's wrapper (requires their permission via /share)",
            )
            .required(false),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::String,
                "mode",
                "Where to run: local (your machine) or cluster (Pi nodes)",
            )
            .required(false)
            .add_string_choice("Local (your machine)", "local")
            .add_string_choice("Cluster (Pi nodes)", "cluster"),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::String,
                "session",
                "Optional session ID to continue a previous session",
            )
            .required(false),
        )
}

/// Handle the /task command.
pub async fn task(ctx: &Context, command: &CommandInteraction, wrapper: &WrapperClient) {
    // Extract user info
    let user_id = command.user.id.to_string();

    // Extract options
    let prompt = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "prompt")
        .and_then(|opt| opt.value.as_str())
        .unwrap_or("")
        .to_string();

    let project = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "project")
        .and_then(|opt| opt.value.as_str())
        .map(|s| s.to_string());

    // Extract target user for collaborative access using Serenity 0.12 API
    let target_user = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "target")
        .and_then(|opt| opt.value.as_user_id())
        .map(|user_id| user_id.to_string());

    let mode = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "mode")
        .and_then(|opt| opt.value.as_str())
        .map(|s| match s {
            "cluster" => ExecutionMode::Cluster,
            _ => ExecutionMode::Local,
        });

    let session_id = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "session")
        .and_then(|opt| opt.value.as_str())
        .map(|s| s.to_string());

    info!(
        "Task command received: user={}, target={:?}, prompt='{}', project={:?}, mode={:?}",
        user_id, target_user, prompt, project, mode
    );

    // Build initial response message
    let mode_str = mode
        .as_ref()
        .map(|m| match m {
            ExecutionMode::Local => " (local)",
            ExecutionMode::Cluster => " (cluster)",
        })
        .unwrap_or("");

    let project_info = project
        .as_ref()
        .map(|p| format!(" on `{}`", p))
        .unwrap_or_default();

    let target_info = target_user
        .as_ref()
        .map(|t| format!(" via <@{}>", t))
        .unwrap_or_default();

    let initial_response = CreateInteractionResponseMessage::new()
        .content(format!(
            "Processing your task{}{}{}...",
            project_info, target_info, mode_str
        ))
        .ephemeral(false);

    if let Err(e) = command
        .create_response(&ctx.http, CreateInteractionResponse::Message(initial_response))
        .await
    {
        error!("Failed to send initial response: {}", e);
        return;
    }

    // Submit task to wrapper service
    let request = TaskRequest {
        prompt: prompt.clone(),
        project,
        session_id,
        working_dir: None,
        discord_user_id: Some(user_id),
        target_user_id: target_user,
        mode,
    };

    match wrapper.submit_task(request).await {
        Ok(response) => {
            let status_emoji = match response.status {
                TaskStatus::Completed => "✅",
                TaskStatus::Failed => "❌",
                TaskStatus::Running => "🔄",
                TaskStatus::Pending => "⏳",
                TaskStatus::NeedsApproval => "⚠️",
            };

            let mut content = format!(
                "{} **Task {}**\n\n**Status:** {}\n**Task ID:** `{}`\n**Session:** `{}`",
                status_emoji,
                response.status,
                response.status,
                response.task_id,
                response.session_id,
            );

            // Add output (truncated if too long for Discord's 2000 char limit)
            if !response.output.is_empty() {
                let max_output_len = 1500; // Leave room for status, task ID, etc.
                let output = if response.output.len() > max_output_len {
                    format!(
                        "{}...\n\n>>> (truncated - {} chars total) <<<\nUse `/status task_id:{}` for full output",
                        &response.output[..max_output_len],
                        response.output.len(),
                        response.task_id
                    )
                } else {
                    response.output.clone()
                };
                content.push_str(&format!("\n\n**Output:**\n```\n{}\n```", output));
            }

            // Add error if present
            if let Some(err) = &response.error {
                content.push_str(&format!("\n\n**Error:**\n```\n{}\n```", err));
            }

            // Add approval request if present
            if let Some(approval) = &response.approval_request {
                content.push_str(&format!(
                    "\n\n**Approval Required:**\n{}\n\nUse `/approve task_id:{} option:<option>` to respond.",
                    approval.description,
                    response.task_id,
                ));
            }

            // Update the response
            let edit = EditInteractionResponse::new().content(content);
            if let Err(e) = command.edit_response(&ctx.http, edit).await {
                error!("Failed to edit response: {}", e);
            }
        }
        Err(e) => {
            error!("Task submission failed: {}", e);

            // Provide helpful error message
            let error_msg = e.to_string();
            let hint = if error_msg.contains("not found") || error_msg.contains("not registered") {
                "\n\n**Hint:** You may need to register first with `/register local url:<your-wrapper-url>`"
            } else {
                ""
            };

            let edit = EditInteractionResponse::new()
                .content(format!("❌ **Task Failed**\n\n```\n{}\n```{}", e, hint));
            if let Err(e) = command.edit_response(&ctx.http, edit).await {
                error!("Failed to edit error response: {}", e);
            }
        }
    }
}
