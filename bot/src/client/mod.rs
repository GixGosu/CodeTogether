//! HTTP client module for wrapper service communication.

mod wrapper;

pub use wrapper::{
    ApprovalSubmission, ExecutionMode, ProjectRequest, RegisterLocalRequest,
    TaskRequest, TaskStatus, WrapperClient,
};
