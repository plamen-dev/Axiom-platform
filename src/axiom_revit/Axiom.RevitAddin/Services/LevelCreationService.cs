using Autodesk.Revit.DB;
using Axiom.Core.Models;

namespace Axiom.RevitAddin.Services
{
    /// <summary>
    /// Service responsible for creating building levels in Revit.
    /// Uses Level.Create(Document, double) — straightforward and deterministic.
    /// </summary>
    public class LevelCreationService
    {
        /// <summary>
        /// Create levels at the specified elevations.
        /// </summary>
        /// <param name="doc">The active Revit document (must be in a transaction).</param>
        /// <param name="parameters">Level creation parameters.</param>
        /// <param name="elevations">Pre-computed elevation array.</param>
        public void CreateLevels(Document doc, LevelParameters parameters, double[] elevations)
        {
            bool hasNames = parameters.LevelNames != null
                && parameters.LevelNames.Length > 0;

            for (int i = 0; i < elevations.Length; i++)
            {
                Level level = Level.Create(doc, elevations[i]);

                if (hasNames && i < parameters.LevelNames.Length)
                {
                    level.Name = parameters.LevelNames[i];
                }
            }
        }
    }
}
