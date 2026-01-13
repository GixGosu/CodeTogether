//! /status command - Check the status of a task.

use serenity::all::{
    CommandInteraction, CommandOptionType, Context, CreateCommand, CreateCommandOption,
    CreateInteractionResponse, CreateInteractionResponseMessage, CreateMessage,
};
use tracing::{error, info};

use crate::client::{TaskStatus, WrapperClient};

/// Create the command registration.
pub fn register() -> CreateCommand {
    CreateCommand::new("status")
        .description("Check the status of a task")
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::String,
                "task_id",
                "The task ID to check",
            )
            .required(true),
        )
}

/// Handle the /status command.
pub async fn status(ctx: &Context, command: &CommandInteraction, wrapper: &WrapperClient) {
    // Get user ID from Discord (server-side, cannot be spoofed)
    let user_id = command.user.id.to_string();

    // Extract task_id
    let task_id = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "task_id")
        .and_then(|opt| opt.value.as_str())
        .unwrap_or("");

    info!(
        "Status command received: task_id='{}', user={}",
        task_id, user_id
    );

    match wrapper.get_task(task_id, &user_id).await {
        Ok(response) => {
            let status_emoji = match response.status {
                TaskStatus::Completed => "✅",
                TaskStatus::Failed => "❌",
                TaskStatus::Running => "🔄",
                TaskStatus::Pending => "⏳",
                TaskStatus::NeedsApproval => "⚠️",
            };

            let mut content = format!(
                "{} **Task Status**\n\n**Status:** {}\n**Task ID:** `{}`\n**Session:** `{}`\n**Created:** {}\n**Updated:** {}",
                status_emoji,
                response.status,
                response.task_id,
                response.session_id,
                response.created_at,
                response.updated_at,
            );

            // Track if we need follow-up messages for full output
            let mut followup_chunks: Vec<String> = Vec::new();

            // Add output if present
            if !response.output.is_empty() {
                let max_initial = 1200; // Leave room for status info
                let max_chunk = 1900;   // Discord limit is 2000

                if response.output.len() <= max_initial {
                    content.push_str(&format!("\n\n**Output:**\n```\n{}\n```", response.output));
                } else {
                    // Calculate remaining length and number of follow-up chunks needed
                    let remaining_len = response.output.len() - max_initial;
                    let followup_count = (remaining_len + max_chunk - 1) / max_chunk; // Ceiling division
                    let total_chunks = 1 + followup_count;

                    // First chunk in initial message
                    content.push_str(&format!(
                        "\n\n**Output (1/{}):**\n```\n{}\n```",
                        total_chunks,
                        &response.output[..max_initial]
                    ));

                    // Split remaining output into chunks
                    let remaining = &response.output[max_initial..];
                    let mut chunk_num = 2;

                    for chunk in remaining.as_bytes().chunks(max_chunk) {
                        let chunk_str = String::from_utf8_lossy(chunk);
                        followup_chunks.push(format!(
                            "**Output ({}/{}):**\n```\n{}\n```",
                            chunk_num, total_chunks, chunk_str
                        ));
                        chunk_num += 1;
                    }
                }
            }

            // Add error if present
            if let Some(err) = &response.error {
                content.push_str(&format!("\n\n**Error:**\n```\n{}\n```", err));
            }

            // Add approval info if present
            if let Some(approval) = &response.approval_request {
                content.push_str(&format!(
                    "\n\n**Awaiting Approval:**\n{}\n\nOptions:\n{}",
                    approval.description,
                    approval
                        .options
                        .iter()
                        .map(|o| format!("- `{}`: {}", o.id, o.label))
                        .collect::<Vec<_>>()
                        .join("\n"),
                ));
            }

            let response_msg = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);

            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response_msg))
                .await
            {
                error!("Failed to send status response: {}", e);
                return;
            }

            // Send follow-up messages for remaining output chunks
            for chunk in followup_chunks {
                let channel_id = command.channel_id;
                if let Err(e) = channel_id
                    .send_message(&ctx.http, CreateMessage::new().content(chunk))
                    .await
                {
                    error!("Failed to send follow-up chunk: {}", e);
                }
            }
        }
        Err(e) => {
            error!("Failed to get task status: {}", e);
            let response_msg = CreateInteractionResponseMessage::new()
                .content(format!("❌ **Failed to get task status**\n\n```\n{}\n```", e))
                .ephemeral(true);

            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response_msg))
                .await
            {
                error!("Failed to send error response: {}", e);
            }
        }
    }
}
