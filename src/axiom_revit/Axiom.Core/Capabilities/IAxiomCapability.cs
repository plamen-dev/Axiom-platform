using System;

namespace Axiom.Core.Capabilities
{
    /// <summary>
    /// Contract for all executable capabilities in Axiom.
    /// Each capability wraps a deterministic Revit action
    /// that the ExecutionAgent can invoke via the pipe bridge.
    /// </summary>
    public interface IAxiomCapability
    {
        /// <summary>
        /// Unique name used in JSON-RPC method dispatch.
        /// Example: "CreateGrids"
        /// </summary>
        string Name { get; }

        /// <summary>
        /// Human-readable description of what this capability does.
        /// </summary>
        string Description { get; }

        /// <summary>
        /// The System.Type of the parameter class this capability expects.
        /// Used for runtime deserialization of the args JSON.
        /// </summary>
        Type ParameterType { get; }

        /// <summary>
        /// Execute the capability against a Revit Document.
        /// </summary>
        /// <param name="doc">The active Revit Document.</param>
        /// <param name="argsJson">JSON string matching ParameterType.</param>
        /// <param name="simulate">If true, validate only — do not modify the model.</param>
        /// <returns>Structured result with status, created IDs, warnings, errors.</returns>
        CapabilityResult Execute(
            Autodesk.Revit.DB.Document doc,
            string argsJson,
            bool simulate);
    }
}
