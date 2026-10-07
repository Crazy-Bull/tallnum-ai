#include <petscksp.h>
#include <array>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using namespace std;

template<class T> T read(ifstream& in) {
    T value{};
    in.read(reinterpret_cast<char*>(&value),sizeof(value));
    if (!in) throw runtime_error("Truncated TNGRAPH1 file");
    return value;
}

int main(int argc,char** argv) {
    PetscInitialize(&argc,&argv,nullptr,nullptr);
    try {
        if (argc<3) throw runtime_error("usage: petsc_graph_eval GRAPH RESULT [PETSc options]");
        ifstream in(argv[1],ios::binary);
        if (!in) throw runtime_error("Cannot open fixed-policy graph");
        array<char,8> magic{};
        in.read(magic.data(),8);
        if (string(magic.data(),8)!="TNGRAPH1") throw runtime_error("Expected TNGRAPH1");
        uint64_t n64=read<uint64_t>(in);
        if (n64<36 || n64>uint64_t(numeric_limits<PetscInt>::max()))
            throw runtime_error("Invalid graph state count");
        PetscInt n=PetscInt(n64);
        vector<uint8_t> kind(n);
        in.read(reinterpret_cast<char*>(kind.data()),n);
        in.seekg(n,ios::cur); // Drop costs are used by the separate moment solver.
        if (!in) throw runtime_error("Truncated graph costs");

        Mat matrix;
        Vec rhs,solution,residual;
        KSP solver;
        PetscCallAbort(PETSC_COMM_SELF,MatCreateSeqAIJ(PETSC_COMM_SELF,n,n,7,nullptr,&matrix));
        PetscCallAbort(PETSC_COMM_SELF,VecCreateSeq(PETSC_COMM_SELF,n,&rhs));
        PetscCallAbort(PETSC_COMM_SELF,VecSet(rhs,0));
        PetscCallAbort(PETSC_COMM_SELF,VecDuplicate(rhs,&solution));
        PetscCallAbort(PETSC_COMM_SELF,VecDuplicate(rhs,&residual));
        for (PetscInt i=0;i<n;++i) {
            if (kind[i]>2) throw runtime_error("Invalid graph terminal kind");
            PetscInt col=i;
            PetscScalar one=1;
            PetscCallAbort(PETSC_COMM_SELF,MatSetValues(matrix,1,&i,1,&col,&one,ADD_VALUES));
            if (kind[i]==0) {
                array<uint32_t,6> successors{};
                in.read(reinterpret_cast<char*>(successors.data()),24);
                if (!in) throw runtime_error("Truncated graph successors");
                for (auto next:successors) {
                    if (next>=n64) throw runtime_error("Graph successor outside state range");
                    col=PetscInt(next);
                    PetscScalar weight=-1.0/6.0;
                    PetscCallAbort(PETSC_COMM_SELF,MatSetValues(matrix,1,&i,1,&col,&weight,ADD_VALUES));
                }
            } else {
                // The stored file has six successor slots even for terminals.
                in.seekg(24,ios::cur);
                if (!in) throw runtime_error("Truncated terminal successor slots");
                if (kind[i]==1)
                    PetscCallAbort(PETSC_COMM_SELF,VecSetValue(rhs,i,1,INSERT_VALUES));
            }
        }
        if (in.peek()!=ifstream::traits_type::eof()) throw runtime_error("Trailing graph data");
        PetscCallAbort(PETSC_COMM_SELF,MatAssemblyBegin(matrix,MAT_FINAL_ASSEMBLY));
        PetscCallAbort(PETSC_COMM_SELF,MatAssemblyEnd(matrix,MAT_FINAL_ASSEMBLY));
        PetscCallAbort(PETSC_COMM_SELF,VecAssemblyBegin(rhs));
        PetscCallAbort(PETSC_COMM_SELF,VecAssemblyEnd(rhs));
        PetscCallAbort(PETSC_COMM_SELF,KSPCreate(PETSC_COMM_SELF,&solver));
        PetscCallAbort(PETSC_COMM_SELF,KSPSetOperators(solver,matrix,matrix));
        PetscCallAbort(PETSC_COMM_SELF,KSPSetFromOptions(solver));
        PetscCallAbort(PETSC_COMM_SELF,KSPSolve(solver,rhs,solution));
        KSPConvergedReason reason;
        PetscInt iterations;
        PetscCallAbort(PETSC_COMM_SELF,KSPGetConvergedReason(solver,&reason));
        PetscCallAbort(PETSC_COMM_SELF,KSPGetIterationNumber(solver,&iterations));
        if (reason<=0) throw runtime_error("PETSc fixed-policy graph solve did not converge");
        PetscCallAbort(PETSC_COMM_SELF,MatMult(matrix,solution,residual));
        PetscCallAbort(PETSC_COMM_SELF,VecAXPY(residual,-1,rhs));
        PetscReal residualInf;
        PetscCallAbort(PETSC_COMM_SELF,VecNorm(residual,NORM_INFINITY,&residualInf));
        const PetscScalar* values;
        PetscCallAbort(PETSC_COMM_SELF,VecGetArrayRead(solution,&values));
        double probability=0;
        for (int i=0;i<36;++i) probability+=PetscRealPart(values[i])/36.0;
        PetscCallAbort(PETSC_COMM_SELF,VecRestoreArrayRead(solution,&values));
        ofstream out(argv[2]);
        out<<setprecision(17)<<"{\"converged\":true,\"states\":"<<n64
           <<",\"successProbability\":"<<probability
           <<",\"iterations\":"<<iterations
           <<",\"residualInf\":"<<residualInf<<"}\n";
        out.close();
        if (!out) throw runtime_error("Cannot write graph PETSc result");
        PetscCallAbort(PETSC_COMM_SELF,KSPDestroy(&solver));
        PetscCallAbort(PETSC_COMM_SELF,VecDestroy(&residual));
        PetscCallAbort(PETSC_COMM_SELF,VecDestroy(&solution));
        PetscCallAbort(PETSC_COMM_SELF,VecDestroy(&rhs));
        PetscCallAbort(PETSC_COMM_SELF,MatDestroy(&matrix));
        PetscFinalize();
        return 0;
    } catch (const exception& error) {
        cerr<<error.what()<<endl;
        PetscFinalize();
        return 1;
    }
}
