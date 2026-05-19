using System;
using System.Diagnostics;

namespace Axiom.RevitAddin.Logging
{
    /// <summary>
    /// Execution logging stub for grid runs.
    /// This class intentionally does NOT write to any database.
    /// It exists only to capture execution metadata for future integration.
    /// </summary>
    public static class ExecutionLogStub
    {
        public static void LogExecution(
            string capabilityId,
            DateTime timestampUtc,
            string parameterSummary,
            string resultStatus)
        {
            // Placeholder behavior only (no persistence)
            Debug.WriteLine("=== Axiom Execution Log Stub ===");
            Debug.WriteLine($"Capability ID : {capabilityId}");
            Debug.WriteLine($"Timestamp UTC : {timestampUtc:O}");
            Debug.WriteLine($"Result Status : {resultStatus}");
            Debug.WriteLine("Parameter Summary:");
            Debug.WriteLine(parameterSummary);
            Debug.WriteLine("================================");
        }
    }
}
