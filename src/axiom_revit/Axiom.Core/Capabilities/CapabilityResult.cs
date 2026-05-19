using System.Collections.Generic;

namespace Axiom.Core.Capabilities
{
    /// <summary>
    /// Structured result returned by every capability execution.
    /// Serialized to JSON and sent back through the pipe bridge.
    /// </summary>
    public class CapabilityResult
    {
        public string Status { get; set; } = "SUCCESS";
        public List<string> CreatedIds { get; set; } = new List<string>();
        public List<string> Warnings { get; set; } = new List<string>();
        public List<string> Errors { get; set; } = new List<string>();
        public long DurationMs { get; set; }
        public Dictionary<string, object> OutputData { get; set; } = new Dictionary<string, object>();
    }
}
