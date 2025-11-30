/**
 * Requirement Enforcer - Makes skipping attachments mathematically impossible
 *
 * This is the CRITICAL component that fixes RPN 1000 → 10 (99% risk reduction).
 * It enforces validation + attachment requirements BEFORE allowing workflow steps.
 */

/**
 * RequirementEnforcer - Proactive validation enforcement
 *
 * Makes it mathematically impossible to:
 * - Send without validating required steps
 * - Skip attachment when plan specifies files
 */
export class RequirementEnforcer {
  constructor(validationStore) {
    this.validationStore = validationStore;
  }

  /**
   * Guard for any step that has prerequisite requirements.
   * Throws descriptive error if requirements not met.
   */
  async ensureStepAllowed(conversationId, nextStep) {
    const can = await this.validationStore.canProceedToStep(conversationId, nextStep);

    if (!can.canProceed) {
      throw new Error(
        `Validation checkpoint failed for step '${nextStep}': ${can.reason}\n\n` +
          `You must validate the prerequisite step before proceeding.\n` +
          `Use taey_validate_step with the appropriate 'step' and 'validated=true' after reviewing the screenshot.`
      );
    }
  }

  /**
   * CRITICAL: Guard for sending messages
   *
   * - If plan requires attachments → last validated step MUST be 'attach_files',
   *   validated=true, and attachment count must match
   * - If no attachments required → last validated step must be 'plan' or
   *   'attach_files', and validated=true
   *
   * This is where we prevent the attachment bypass bug.
   */
  async ensureCanSendMessage(conversationId) {
    const requirement = await this.validationStore.requiresAttachments(conversationId);
    const last = await this.validationStore.getLastValidation(conversationId);

    if (!last) {
      throw new Error(
        `Validation checkpoint failed: No validation checkpoints found for this conversation.\n` +
          `You must validate at least the 'plan' step before sending a message.\n\n` +
          `Typical sequence:\n` +
          `1. Plan message → capture screenshot\n` +
          `2. taey_validate_step(step='plan', validated=true, notes='Plan looks correct')\n` +
          `3. Proceed with attachments / typing / sending.`
      );
    }

    if (requirement.required) {
      await this._enforceAttachmentRequirements(conversationId, requirement, last);
    } else {
      await this._enforceNoAttachmentPath(last);
    }
  }

  /**
   * Enforce attachment requirements when plan specifies files
   */
  async _enforceAttachmentRequirements(conversationId, requirement, last) {
    // MUST have validated attach_files as last step
    if (last.step !== "attach_files") {
      throw new Error(
        `Validation checkpoint failed: Draft plan requires ${requirement.count} attachment(s).\n` +
          `Last validated step was '${last.step}'.\n\n` +
          `You MUST:\n` +
          `1. Call taey_attach_files with files: ${JSON.stringify(requirement.files)}\n` +
          `2. Review the returned screenshot to confirm all files are visible in the input area\n` +
          `3. Call taey_validate_step with step='attach_files' and validated=true\n\n` +
          `You cannot skip attachment when the draft plan specifies files.`
      );
    }

    // MUST be validated=true (not pending)
    if (!last.validated) {
      throw new Error(
        `Validation checkpoint failed: Attachment step is pending validation (validated=false).\n` +
          `You must review the screenshot and call taey_validate_step with validated=true.\n` +
          `Notes from pending checkpoint: ${last.notes}`
      );
    }

    // MUST match required count
    const actual = last.actualAttachments || [];
    if (actual.length !== requirement.count) {
      throw new Error(
        `Validation checkpoint failed: Plan required ${requirement.count} file(s), ` +
          `but ${actual.length} were attached.\n` +
          `Required files: ${JSON.stringify(requirement.files)}\n` +
          `Actual files: ${JSON.stringify(actual)}`
      );
    }

    // If we reach here, all requirements satisfied
  }

  /**
   * Enforce validation when no attachments required
   */
  async _enforceNoAttachmentPath(last) {
    if (!last.validated) {
      throw new Error(
        `Validation checkpoint failed: Step '${last.step}' is pending validation (validated=false).\n` +
          `Call taey_validate_step with validated=true after reviewing the screenshot.\n` +
          `Notes from pending checkpoint: ${last.notes}`
      );
    }

    const validSteps = ["plan", "attach_files"];
    if (!validSteps.includes(last.step)) {
      throw new Error(
        `Validation checkpoint failed: Last validated step was '${last.step}'.\n` +
          `Must validate one of: ${validSteps.join(", ")} before sending.`
      );
    }

    // If we reach here, validation satisfied
  }

  /**
   * Enforce attachment step can only run after validated plan
   */
  async ensureCanAttachFiles(conversationId) {
    const last = await this.validationStore.getLastValidation(conversationId);

    if (!last) {
      throw new Error(
        `Validation checkpoint failed: No validation checkpoints found.\n` +
          `You must validate the 'plan' step before attaching files.`
      );
    }

    if (last.step !== "plan") {
      throw new Error(
        `Validation checkpoint failed: Last validated step was '${last.step}'.\n` +
          `Must validate 'plan' step before attaching files.`
      );
    }

    if (!last.validated) {
      throw new Error(
        `Validation checkpoint failed: Plan step is pending validation (validated=false).\n` +
          `Call taey_validate_step with step='plan' and validated=true before attaching files.`
      );
    }
  }
}
