using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

using Axiom.Core.Models;
using Axiom.RevitAddin.Services;
using Axiom.RevitAddin.UI;
using Axiom.RevitAddin.Logging;

namespace Axiom.RevitAddin
{
    [Transaction(TransactionMode.Manual)]
    public class GridsCommand : IExternalCommand
    {
        private const double DefaultTailFeet = 10.0;
        private const string CapabilityId = "revit_grid_creation";

        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            UIDocument uiDoc = commandData.Application.ActiveUIDocument;
            if (uiDoc == null)
            {
                TaskDialog.Show(
                    "Axiom - Grid Creation Failed",
                    "Reason:\nNo active Revit document was found.\n\n" +
                    "Action:\nOpen a Revit project and try again.\n\n" +
                    "Model status:\nNo changes were made."
                );
                return Result.Failed;
            }

            Document doc = uiDoc.Document;
            View view = doc.ActiveView;

            if (!(view is ViewPlan) || view.IsTemplate)
            {
                TaskDialog.Show(
                    "Axiom - Grid Creation Failed",
                    "Reason:\nGrid creation is only allowed in plan views.\n\n" +
                    "Action:\nOpen a Floor Plan or Ceiling Plan and try again.\n\n" +
                    "Model status:\nNo changes were made."
                );

                ExecutionLogStub.LogExecution(
                    CapabilityId,
                    DateTime.UtcNow,
                    "N/A (invalid view)",
                    "Failed"
                );

                return Result.Failed;
            }

            GridParameters parameters;
            if (!GridPromptDialog.TryGetParameters(null, out parameters))
            {
                TaskDialog.Show(
                    "Axiom - Grid Creation Cancelled",
                    "Reason:\nThe operation was cancelled by the user.\n\n" +
                    "Action:\nRe-run the command if you want to create grids.\n\n" +
                    "Model status:\nNo changes were made."
                );
                return Result.Cancelled;
            }

            if (parameters.HorizontalCount <= 0 || parameters.VerticalCount <= 0)
            {
                TaskDialog.Show(
                    "Axiom - Grid Creation Failed",
                    "Reason:\nGrid counts must be greater than zero.\n\n" +
                    "Action:\nSet both Horizontal and Vertical counts to at least 1.\n\n" +
                    "Model status:\nNo changes were made."
                );

                ExecutionLogStub.LogExecution(
                    CapabilityId,
                    DateTime.UtcNow,
                    "Invalid grid counts",
                    "Failed"
                );

                return Result.Failed;
            }

            if (parameters.SpacingFeet <= 0)
            {
                TaskDialog.Show(
                    "Axiom - Grid Creation Failed",
                    "Reason:\nGrid spacing must be greater than zero.\n\n" +
                    "Action:\nEnter a spacing value greater than 0.\n\n" +
                    "Model status:\nNo changes were made."
                );

                ExecutionLogStub.LogExecution(
                    CapabilityId,
                    DateTime.UtcNow,
                    "Invalid spacing",
                    "Failed"
                );

                return Result.Failed;
            }

            string numericPattern = @"^\d+$";
            string alphabeticPattern = @"^[A-Z]+$";

            List<string> expectedNumericNames =
                Enumerable.Range(1, parameters.HorizontalCount)
                          .Select(i => i.ToString())
                          .ToList();

            List<string> expectedAlphabeticNames =
                Enumerable.Range(0, parameters.VerticalCount)
                          .Select(i => GetAlphabeticName(i))
                          .ToList();

            if (expectedNumericNames.Any(n => !Regex.IsMatch(n, numericPattern)) ||
                expectedAlphabeticNames.Any(n => !Regex.IsMatch(n, alphabeticPattern)))
            {
                TaskDialog.Show(
                    "Axiom - Grid Creation Failed",
                    "Reason:\nGenerated grid names are invalid.\n\n" +
                    "Action:\nVerify grid counts to ensure valid numeric and alphabetic naming.\n\n" +
                    "Model status:\nNo changes were made."
                );

                ExecutionLogStub.LogExecution(
                    CapabilityId,
                    DateTime.UtcNow,
                    "Invalid naming pattern",
                    "Failed"
                );

                return Result.Failed;
            }

            double derivedHorizontalSpan =
                (parameters.HorizontalCount - 1) * parameters.SpacingFeet;

            double derivedVerticalSpan =
                (parameters.VerticalCount - 1) * parameters.SpacingFeet;

            if (DefaultTailFeet <= 0 || derivedHorizontalSpan <= 0 || derivedVerticalSpan <= 0)
            {
                TaskDialog.Show(
                    "Axiom - Grid Creation Failed",
                    "Reason:\nDerived grid extents are invalid.\n\n" +
                    "Action:\nIncrease grid counts and/or spacing so derived spans are positive.\n\n" +
                    "Model status:\nNo changes were made."
                );

                ExecutionLogStub.LogExecution(
                    CapabilityId,
                    DateTime.UtcNow,
                    "Invalid derived geometry",
                    "Failed"
                );

                return Result.Failed;
            }

            HashSet<string> existingNames =
                new FilteredElementCollector(doc)
                    .OfClass(typeof(Grid))
                    .Cast<Grid>()
                    .Select(g => g.Name)
                    .ToHashSet(StringComparer.OrdinalIgnoreCase);

            var conflicts =
                expectedNumericNames.Concat(expectedAlphabeticNames)
                                    .Where(n => existingNames.Contains(n))
                                    .ToList();

            if (conflicts.Any())
            {
                TaskDialog.Show(
                    "Axiom - Grid Creation Failed",
                    "Reason:\nSome grid names already exist in this model.\n\n" +
                    "Action:\nRemove or rename existing grids, then try again.\n\n" +
                    "Model status:\nNo changes were made."
                );

                ExecutionLogStub.LogExecution(
                    CapabilityId,
                    DateTime.UtcNow,
                    "Duplicate grid names",
                    "Failed"
                );

                return Result.Failed;
            }

            string parameterSummary =
                BuildParameterSummary(parameters, DefaultTailFeet, derivedHorizontalSpan, derivedVerticalSpan);

            Transaction tx = new Transaction(doc, "Axiom - Create Grids");

            try
            {
                tx.Start();

                GridCreationService service = new GridCreationService();
                service.CreateHorizontalGrids(doc, parameters);

                tx.Commit();

                ExecutionLogStub.LogExecution(
                    CapabilityId,
                    DateTime.UtcNow,
                    parameterSummary,
                    "Succeeded"
                );

                TaskDialog.Show(
                    "Axiom - Grid Creation Complete",
                    "Grid creation succeeded.\n\n" +
                    parameterSummary
                );

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                if (tx.HasStarted())
                    tx.RollBack();

                ExecutionLogStub.LogExecution(
                    CapabilityId,
                    DateTime.UtcNow,
                    parameterSummary,
                    "Failed"
                );

                TaskDialog.Show(
                    "Axiom - Grid Creation Failed",
                    "Reason:\nAn unexpected error occurred during grid creation.\n\n" +
                    "Action:\nReview the error details and try again.\n\n" +
                    "Model status:\nNo changes were made.\n\n" +
                    $"Details:\n{ex.Message}"
                );

                return Result.Failed;
            }
            finally
            {
                tx.Dispose();
            }
        }

        private static string BuildParameterSummary(
            GridParameters p,
            double tailFeet,
            double spanXFeet,
            double spanYFeet)
        {
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("Final Parameters Used");
            sb.AppendLine("---------------------");
            sb.AppendLine($"Horizontal Count : {p.HorizontalCount}");
            sb.AppendLine($"Vertical Count   : {p.VerticalCount}");
            sb.AppendLine($"Spacing (ft)     : {p.SpacingFeet}");
            sb.AppendLine($"Tail (ft)        : {tailFeet}");
            sb.AppendLine($"Full Span X (ft) : {spanXFeet}");
            sb.AppendLine($"Full Span Y (ft) : {spanYFeet}");
            sb.AppendLine($"Length           : {(p.Length > 0 ? p.Length.ToString() : "Derived")}");
            sb.AppendLine($"Naming           : {p.Naming}");
            return sb.ToString();
        }

        private static string GetAlphabeticName(int index)
        {
            string name = string.Empty;
            index++;
            while (index > 0)
            {
                int r = (index - 1) % 26;
                name = (char)('A' + r) + name;
                index = (index - 1) / 26;
            }
            return name;
        }
    }
}
