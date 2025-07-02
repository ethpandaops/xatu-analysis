from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

class BeaconchainResponse(BaseModel):
    """Base response wrapper for all API responses"""
    status: str
    data: Any

class ValidatorInfo(BaseModel):
    """Basic validator information"""
    pubkey: str
    validatorindex: int = Field(alias="validatorindex")
    balance: int
    effective_balance: int
    slashed: bool
    activation_eligibility_epoch: int
    activation_epoch: int
    exit_epoch: int
    last_attestation_slot: int
    name: Optional[str] = None
    status: str
    withdrawable_epoch: int
    withdrawal_credentials: str

class ValidatorPerformance(BaseModel):
    """Validator performance metrics"""
    validatorindex: int
    balance: int
    performance1d: int
    performance7d: int
    performance31d: int
    performance365d: int
    rank7d: int

class ValidatorExecutionPerformance(BaseModel):
    """Execution layer performance"""
    validatorindex: int
    performance1d: int
    performance7d: int
    performance31d: int

class ValidatorIncomeDetail(BaseModel):
    """Detailed income breakdown"""
    attestation_head_reward: int
    attestation_source_reward: int
    attestation_source_penalty: int
    attestation_target_reward: int
    attestation_target_penalty: int
    finality_delay_penalty: int
    proposer_attestation_inclusion_reward: int
    proposer_slashing_inclusion_reward: int
    proposer_sync_inclusion_reward: int
    sync_committee_reward: int
    sync_committee_penalty: int
    slashing_reward: int
    slashing_penalty: int
    proposals_missed: int
    tx_fee_reward_wei: Optional[str] = None

class ValidatorIncomeHistory(BaseModel):
    """Income history entry"""
    validatorindex: int
    epoch: int
    week: int
    week_start: str
    week_end: str
    income: ValidatorIncomeDetail

class ValidatorProposal(BaseModel):
    """Proposed block information"""
    epoch: int
    slot: int
    blockroot: str
    parentroot: str
    stateroot: str
    signature: str
    graffiti: str
    graffiti_text: str
    attestationscount: int
    depositscount: int
    voluntaryexitscount: int
    attesterslashingscount: int
    proposerslashingscount: int
    withdrawalcount: int
    syncaggregate_bits: str
    syncaggregate_participation: float
    syncaggregate_signature: str
    status: str
    proposer: int
    exec_block_number: Optional[int] = None
    exec_block_hash: Optional[str] = None
    exec_parent_hash: Optional[str] = None
    exec_fee_recipient: Optional[str] = None
    exec_gas_limit: Optional[int] = None
    exec_gas_used: Optional[int] = None
    exec_base_fee_per_gas: Optional[int] = None
    exec_timestamp: Optional[int] = None
    exec_random: Optional[str] = None
    exec_extra_data: Optional[str] = None
    exec_transactions_count: Optional[int] = None

class ValidatorWithdrawal(BaseModel):
    """Withdrawal information"""
    validatorindex: int
    withdrawalindex: int
    address: str
    amount: int
    epoch: int
    slot: int
    blockroot: str

class ValidatorDailyStats(BaseModel):
    """Daily statistics"""
    validatorindex: int
    day: int
    day_start: str
    day_end: str
    start_balance: int
    end_balance: int
    start_effective_balance: int
    end_effective_balance: int
    min_balance: int
    max_balance: int
    min_effective_balance: int
    max_effective_balance: int
    missed_attestations: int
    missed_blocks: int
    missed_sync: int
    orphaned_attestations: int
    orphaned_blocks: int
    orphaned_sync: int
    participated_sync: int
    proposed_blocks: int
    attester_slashings: int
    proposer_slashings: int
    deposits: int
    deposits_amount: int
    withdrawals: int
    withdrawals_amount: int